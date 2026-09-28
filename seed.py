"""Posts synthetic seed notes through the API (not the database)."""
import json, sys, time, httpx
base = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
for n in json.load(open("seed_notes.json"))["notes"]:
    r = httpx.post(f"{base}/api/note", json=n, timeout=30); print(n["day"], n["author"], r.json())
    time.sleep(0.3)
