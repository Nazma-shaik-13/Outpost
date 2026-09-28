import os, re, time, queue, threading, collections
from datetime import datetime
import asyncio
from hindsight_client import Hindsight
import database as db

BANK = "field-camp"
URL = os.getenv("HINDSIGHT_API_URL", "http://localhost:8888")
KEY = os.getenv("HINDSIGHT_API_KEY") or None
client = Hindsight(base_url=URL, api_key=KEY, timeout=60.0)
EVENTS = collections.deque(maxlen=100)
_q = queue.Queue()
_pending = set()          # note ids queued or in flight, so the sync loop never double-queues
SYNC_EVERY = 20           # seconds between checks for notes Hindsight has not received

def log(kind, msg):
    EVENTS.append({"t": datetime.now().strftime("%H:%M:%S"), "kind": kind, "msg": msg})

def retry(fn, *a, **k):
    err = None
    for i in range(3):  # 1 try + 2 retries
        try: return fn(*a, **k)
        except Exception as e: err = e; time.sleep(1)
    raise err

def fmt(n):
    return f"[Day {n['day']} | {n['time']}]\n{n['author']}\n({n['role']},\n{n['trust']})\n\n{n['text']}"

def healthy():
    try: client.get_version(); return True
    except Exception: return False

def ensure_bank():
    try:
        retry(client.create_bank, bank_id=BANK, name="Field camp memory",
              mission="Shared institutional memory of a remote camp: safety, equipment, medical, water and supply reports.")
        log("info", f"bank '{BANK}' ready")
    except Exception as e:
        log("error", f"bank setup failed: {e}")

def enqueue(n):
    if n["id"] in _pending:
        return
    _pending.add(n["id"]); _q.put(n)
    log("retain queued", f"Day {n['day']} {n['author']}")

def _retain_once(n):
    async def go():
        c = Hindsight(base_url=URL, api_key=KEY, timeout=120.0)
        try:
            await c.aretain(bank_id=BANK, content=fmt(n), context="field camp report",
                            document_id=f"note-{n['id']}",
                            metadata={"note_id": str(n["id"]), "day": str(n["day"])},
                            retain_async=False)
        finally:
            await c.aclose()
    asyncio.run(go())

def _worker():
    while True:
        n = _q.get()
        try:
            retry(_retain_once, n)
            db.mark_synced(n["id"])
            log("retain complete", f"Day {n['day']} {n['author']}")
        except Exception as e:
            log("error", f"retain failed, will retry when Hindsight is reachable: {type(e).__name__}")
        finally:
            _pending.discard(n["id"])

def _sync_loop():
    """Re-send notes that never reached Hindsight (posted while it was unreachable)."""
    while True:
        time.sleep(SYNC_EVERY)
        try:
            todo = [n for n in db.unsynced() if n["id"] not in _pending]
            if todo and healthy():
                log("sync", f"re-sending {len(todo)} note(s) to Hindsight")
                for n in todo:
                    enqueue(n)
        except Exception as e:
            log("error", f"sync check failed: {type(e).__name__}")

def start():
    threading.Thread(target=_worker, daemon=True).start()
    threading.Thread(target=_sync_loop, daemon=True).start()

def recall(q):
    log("recall query", q)
    resp = retry(client.recall, bank_id=BANK, query=q, budget="low", include_chunks=True, max_chunk_tokens=500)
    log("recall hits", str(len(resp.results)))
    return resp

def reflect(q):
    log("reflect", "started")
    a = retry(client.reflect, bank_id=BANK, query=q, budget="low")
    log("reflect", "complete")
    return a.text