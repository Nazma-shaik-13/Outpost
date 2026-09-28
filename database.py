import sqlite3, threading
from datetime import datetime
DB = "airgap.db"
_lock = threading.Lock()

def _c():
    c = sqlite3.connect(DB, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c

def init():
    with _lock:
        c = _c()
        c.execute("""CREATE TABLE IF NOT EXISTS notes(
            id INTEGER PRIMARY KEY, day INTEGER, time TEXT, author TEXT, role TEXT,
            trust TEXT, text TEXT, source TEXT, created_at TEXT)""")
        cols = [r["name"] for r in c.execute("PRAGMA table_info(notes)")]
        if "synced" not in cols:
            c.execute("ALTER TABLE notes ADD COLUMN synced INTEGER DEFAULT 0")
            # rows that existed before this column were already retained in Hindsight
            c.execute("UPDATE notes SET synced=1")
        c.commit(); c.close()

def add(day, time, author, role, trust, text, source="note"):
    with _lock:
        c = _c()
        cur = c.execute("INSERT INTO notes(day,time,author,role,trust,text,source,created_at,synced) VALUES(?,?,?,?,?,?,?,?,0)",
                        (day, time, author, role, trust, text, source, datetime.now().isoformat()))
        c.commit(); i = cur.lastrowid; c.close()
        return i

def _q(sql, a=()):
    with _lock:
        c = _c(); rows = [dict(r) for r in c.execute(sql, a).fetchall()]; c.close()
        return rows

def mark_synced(i):
    with _lock:
        c = _c(); c.execute("UPDATE notes SET synced=1 WHERE id=?", (i,)); c.commit(); c.close()

def unsynced(): return _q("SELECT * FROM notes WHERE synced=0 ORDER BY id")
def get(i):
    r = _q("SELECT * FROM notes WHERE id=?", (i,)); return r[0] if r else None
def all_notes(): return _q("SELECT * FROM notes ORDER BY day, time, id")
def count(): return _q("SELECT COUNT(*) n FROM notes")[0]["n"]
def has_source(s): return bool(_q("SELECT 1 FROM notes WHERE source=? LIMIT 1", (s,)))