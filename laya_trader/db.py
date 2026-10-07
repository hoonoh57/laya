import datetime as dt
import json
import sqlite3
import threading


class DB:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.c = sqlite3.connect(str(path), check_same_thread=False)
        self.lock = threading.Lock()
        with self.lock:
            self.c.executescript("""
                CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,
                                                  ts TEXT, kind TEXT, data TEXT);
                CREATE INDEX IF NOT EXISTS ix_events_kind ON events(kind, id);
            """)
            self.c.commit()

    def get(self, key, default=None):
        with self.lock:
            row = self.c.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key, value):
        with self.lock:
            self.c.execute("INSERT OR REPLACE INTO kv(key, value) VALUES(?, ?)",
                           (key, json.dumps(value, ensure_ascii=False, default=str)))
            self.c.commit()

    def add_event(self, kind, data) -> dict:
        ts = dt.datetime.now().isoformat(timespec="seconds")
        with self.lock:
            cur = self.c.execute("INSERT INTO events(ts, kind, data) VALUES(?, ?, ?)",
                                 (ts, kind, json.dumps(data, ensure_ascii=False, default=str)))
            self.c.commit()
        return {"id": cur.lastrowid, "ts": ts, "kind": kind, "data": data}

    def events(self, kind, limit=100):
        with self.lock:
            rows = self.c.execute("SELECT id, ts, kind, data FROM events WHERE kind=? ORDER BY id DESC LIMIT ?",
                                  (kind, limit)).fetchall()
        return [{"id": r[0], "ts": r[1], "kind": r[2], "data": json.loads(r[3])} for r in reversed(rows)]
