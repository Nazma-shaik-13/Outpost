from dotenv import load_dotenv
load_dotenv()
import re, threading, datetime as dt
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FTimeout
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, Query
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
import database as db, memory, llm
from replay import build_replay

ROLES = ["Site medic", "Safety officer", "Team lead", "Crew member", "Manual"]
TRUSTS = ["Verified by safety officer", "Verified by team lead", "Unverified observation", "Official document"]
NONE = "No source found in team memory."
ASK_SYS = ("You answer questions for a remote camp using ONLY the notes provided. "
           "Answer in 1-2 short sentences and end with the citation in this exact form: (Day N, Author, Trust). "
           "Notes are in time order: the LAST note is the most recent and gives the current status. "
           "If an older note conflicts, the newer note wins; say the status changed. "
           "Never claim a status changed back unless a note says so. Never add facts that are not in the notes. "
           f"If the notes do not answer the question, reply exactly: {NONE}")
REPLAY_RULES = ("Write a day-by-day timeline of the last 7 days using only the notes. Format: 'Day N:' then short lines. "
                "When a status changes over time (e.g. water source safe then contaminated), add a line: "
                "'Status changed: <thing> changed from <old> to <new>.' Do not invent facts.")
_cache = {"count": -1, "data": None}
_pool = ThreadPoolExecutor(2)

def boot():
    memory.ensure_bank()
    p = Path("manual_generator.md")
    if p.exists() and not db.has_source(p.name):
        ingest(p.name, p.read_text())

def ingest(name, text):
    chunks = [text[i:i + 800] for i in range(0, len(text), 800)]
    for c in chunks:
        i = db.add(0, "00:00", "Manual", "Manual", "Official document", c, name)
        memory.enqueue(db.get(i))
    return len(chunks)

@asynccontextmanager
async def lifespan(app):
    db.init(); memory.start(); threading.Thread(target=boot, daemon=True).start(); yield

app = FastAPI(lifespan=lifespan)

class Note(BaseModel):
    author: str; role: str; trust: str; day: int; text: str

@app.get("/")
def index(): return FileResponse("static/index.html")

@app.post("/api/note")
def note(n: Note):
    if n.role not in ROLES[:4] or n.trust not in TRUSTS:
        return JSONResponse({"status": "error", "error": "Choose a valid role and trust label."}, 400)
    if not n.text.strip() or not n.author.strip():
        return JSONResponse({"status": "error", "error": "Name and text are required."}, 400)
    i = db.add(n.day, dt.datetime.now().strftime("%H:%M"), n.author.strip(), n.role, n.trust, n.text.strip())
    memory.enqueue(db.get(i))
    return {"status": "saving"}

def resolve(resp):
    """Map recalled memories back to SQLite notes (document_id first, then day+author match)."""
    notes, out, seen = db.all_notes(), [], set()
    for r in resp.results:
        m = re.match(r"note-(\d+)", str(getattr(r, "document_id", "") or ""))
        hit = next((n for n in notes if m and n["id"] == int(m.group(1))), None)
        if not hit:
            ch = (resp.chunks or {}).get(getattr(r, "chunk_id", None))
            txt = ch.text if ch else r.text
            d = re.search(r"\[Day (\d+)", txt)
            cands = [n for n in notes if d and n["day"] == int(d.group(1)) and n["author"] in txt] or \
                    [n for n in notes if n["text"][:40] in txt]
            hit = cands[0] if cands else None
        if hit and hit["id"] not in seen:
            seen.add(hit["id"]); out.append(hit)
    return out
def rank(srcs, q, ans):
    stop = {"where", "what", "when", "which", "that", "this", "with", "from", "have", "does", "about"}
    w = lambda s: {x for x in re.findall(r"[a-z0-9]+", s.lower()) if len(x) > 3} - stop
    qa = w(q + " " + ans)
    sc = [(len(qa & w(n["text"])), n) for n in srcs]
    top = max((s for s, _ in sc), default=0)
    return [n for s, n in sorted(sc, key=lambda t: -t[0]) if s >= max(1, top * 0.75)][:3]

_STOP = {"where", "what", "when", "which", "that", "this", "with", "from", "have", "does", "about", "there", "open", "much", "many"}
def _w(s): return {x[:5] for x in re.findall(r"[a-z0-9]+", s.lower()) if len(x) > 3} - {x[:5] for x in _STOP}
def lexical(q, k=3):
    """Keyword match over SQLite so a fresh note is never missed by recall."""
    qw = _w(q)
    sc = [(len(qw & _w(n["text"])), n) for n in db.all_notes()]
    return [n for s_, n in sorted(sc, key=lambda t: (-t[0], -t[1]["day"], -t[1]["id"]))
    if s_ > 0 and (n["day"] > 0 or s_ >= 2)][:k]
def cite(n):
    return f"({n['source']}, {n['trust']})" if n["day"] == 0 else f"(Day {n['day']}, {n['author']}, {n['trust']})"
@app.get("/api/ask")
def ask(q: str, mem: str = Query("on", alias="memory")):
    try:
        if mem == "off":
            return {"answer": llm.chat("You are a helpful assistant. Answer briefly.", q), "sources": []}
        try:
            srcs = resolve(memory.recall(q))
        except Exception as e:
            memory.log("error", f"recall failed, using local notes: {type(e).__name__}")
            srcs = []
        seen = {n["id"] for n in srcs}
        srcs = srcs[:4] + [n for n in lexical(q) if n["id"] not in seen]
        if not srcs: return {"answer": NONE, "sources": []}
        srcs.sort(key=lambda n: (n["day"], n["time"], n["id"]))
        ctx = "\n\n".join(memory.fmt(n) for n in srcs)
        ans = llm.chat(ASK_SYS, f"Notes:\n{ctx}\n\nQuestion: {q}")
        if ans.strip().startswith("No source found"):
            return {"answer": NONE, "sources": []}
        srcs = rank(srcs, q, ans)
        ans = re.sub(r"\s*\((?:Day|Days)[^)]*\)", "", ans).strip()
        ans += "  " + " ".join(cite(n) for n in srcs)
        return {"answer": ans, "sources": [{**{k: n[k] for k in ("day", "author", "role", "trust")}, "text": n["text"][:300]} for n in srcs]}
    except Exception as e:
        memory.log("error", str(e))
        return {"answer": f"The local model did not respond ({e}). Try again in a moment.", "sources": []}

@app.get("/api/replay")
def replay():
    return {"timeline": build_replay(db.all_notes()), "via": "deterministic"}

@app.post("/api/manual")
async def manual(file: UploadFile = File(...)):
    if not file.filename.lower().endswith((".txt", ".md")):
        return JSONResponse({"status": "error", "error": "Only .txt and .md files are accepted."}, 400)
    text = (await file.read()).decode("utf-8", errors="replace")
    return {"status": "saving", "chunks": ingest(file.filename, text)}

@app.get("/api/notes")
def notes_all(): return [n for n in db.all_notes() if n["day"] > 0]

@app.get("/api/log")
def log(): return list(memory.EVENTS)

@app.get("/api/health")
def health(): return {"hindsight": memory.healthy(), "llm": llm.healthy(), "notes": db.count()}

app.mount("/static", __import__("fastapi.staticfiles", fromlist=["x"]).StaticFiles(directory="static"), name="static")