"""Laya 판단(st_entry_v1) + 스냅샷 저장.
질문 스키마는 향후 파인튜닝 데이터와 '정확히' 같아야 한다(키, 문구, 옵션). 바꾸면 SCHEMA 버전을 올릴 것."""
import json
import sqlite3
import threading
import time
from importlib import metadata
from pathlib import Path

SCHEMA = "st_entry_v1"
QUESTIONS = {
    "entry": {
        "type": "choice",
        "instructions": ("A SuperTrend up-turn signal is evaluated on the strategy tick bar. "
                         "If we buy now and exit at the next SuperTrend down-turn, will the trade end in profit?"),
        "criteria": {
            "A": "yes, profit: trend, momentum, order book and peers support continuation",
            "B": "no, loss: weak, late, exhausted or conflicting setup",
        },
    },
    "basis": {
        "type": "choice",
        "instructions": "Which evidence matters most for this decision?",
        "criteria": {
            "trend": "SuperTrend distance and JMA direction",
            "momentum": "recent returns, volume surge and bar speed",
            "orderbook": "bid-ask imbalance and spread",
            "peers": "strength versus other watched stocks",
            "timing": "time of day and position in the day range",
        },
    },
    "regime": {
        "type": "choice",
        "instructions": "What is the current intraday regime for this symbol?",
        "criteria": {
            "trend": "clear directional trend",
            "range": "sideways, mean-reverting",
            "volatile": "unstable, large swings",
        },
    },
    "quality": {
        "type": "score",
        "instructions": "How strong is this entry setup overall?",
        "criteria": ["weak", "moderate", "strong"],
    },
}


def _clean(x):
    if isinstance(x, dict):
        return {str(k): _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    if x is None or isinstance(x, (str, int, float, bool)):
        return x
    try:
        return float(x)
    except Exception:
        return str(x)


def _probs(ans, options):
    for k in ("probabilities", "distribution", "probs"):
        d = ans.get(k)
        if isinstance(d, dict) and d:
            return {o: float(d.get(o, 0.0)) for o in options}
    ch = ans.get("choice")
    conf = float(ans.get("answer_confidence", ans.get("confidence", 0.0)) or 0.0)
    if ch in options and len(options) > 1:
        rest = (1 - conf) / (len(options) - 1)
        return {o: (conf if o == ch else rest) for o in options}
    return {o: 0.0 for o in options}


class Judge:
    def __init__(self, gate):
        self.router, self.model, self.max_len = gate.router, gate.model, gate.max_len
        try:
            ver = metadata.version("laya")
        except Exception:
            ver = "?"
        self.ckpt = f"laya {ver} / {self.model}"

    def __call__(self, state):
        t0 = time.perf_counter()
        res = self.router.predict(state, QUESTIONS, model=self.model, max_len=self.max_len)
        ms = (time.perf_counter() - t0) * 1000
        a = res["answers"]
        e = _probs(a["entry"], ["A", "B"])
        q = a["quality"].get("score")
        return {
            "schema": SCHEMA, "ckpt": self.ckpt, "latency_ms": round(ms, 1),
            "p_entry": round(e["A"], 4),
            "entry_conf": round(float(a["entry"].get("answer_confidence", a["entry"].get("confidence", 0.0)) or 0.0), 4),
            "basis": a["basis"].get("choice"),
            "basis_p": {k: round(v, 4) for k, v in _probs(a["basis"], list(QUESTIONS["basis"]["criteria"])).items()},
            "regime": a["regime"].get("choice"),
            "regime_p": {k: round(v, 4) for k, v in _probs(a["regime"], list(QUESTIONS["regime"]["criteria"])).items()},
            "quality": round(float(q), 4) if q is not None else None,
            "answers": _clean(a),
        }


def _j(x):
    return None if x is None else json.dumps(x, ensure_ascii=False, separators=(",", ":"))


COLS = ("created", "source", "run_id", "code", "kind", "period", "date", "seq", "t", "schema", "ckpt",
        "p_entry", "quality", "basis", "regime", "approved", "latency_ms",
        "params", "f", "state", "window", "judge", "outcome")
JSON_COLS = ("params", "f", "state", "window", "judge", "outcome")


class SnapStore:
    """판단 스냅샷. source: live(장중) / replay(장후 재생). 같은 봉·스키마·체크포인트는 덮어씀"""

    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.con = sqlite3.connect(str(path), check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.execute("""CREATE TABLE IF NOT EXISTS snapshots(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created TEXT, source TEXT, run_id TEXT, code TEXT, kind TEXT, period INTEGER,
            date INTEGER, seq INTEGER, t INTEGER, schema TEXT, ckpt TEXT,
            p_entry REAL, quality REAL, basis TEXT, regime TEXT, approved INTEGER, latency_ms REAL,
            params TEXT, f TEXT, state TEXT, window TEXT, judge TEXT, outcome TEXT,
            UNIQUE(source, code, kind, period, date, seq, schema, ckpt))""")
        self.con.execute("CREATE INDEX IF NOT EXISTS ix_snap_day ON snapshots(date, code)")
        self.con.commit()

    def save(self, source, run_id, snap, judge, approved, outcome=None):
        f = snap["f"]
        row = (time.strftime("%Y-%m-%d %H:%M:%S"), source, run_id, snap["code"], snap["kind"], snap["period"],
               f["date"], f["seq"], f["t"], judge["schema"], judge["ckpt"],
               judge["p_entry"], judge["quality"], judge["basis"], judge["regime"], int(bool(approved)),
               judge["latency_ms"], _j(snap.get("params")), _j(f), _j(snap["state"]), _j(snap["window"]),
               _j(judge), _j(outcome))
        sql = "INSERT OR REPLACE INTO snapshots({}) VALUES({})".format(",".join(COLS), ",".join("?" * len(COLS)))
        with self.lock:
            cur = self.con.execute(sql, row)
            self.con.commit()
            return cur.lastrowid

    def set_outcome(self, sid, outcome):
        with self.lock:
            self.con.execute("UPDATE snapshots SET outcome=? WHERE id=?", (_j(outcome), sid))
            self.con.commit()

    def rows(self, date=None, code=None, source=None, run_id=None, limit=1000):
        w, a = [], []
        for k, v in (("date", date), ("code", code), ("source", source), ("run_id", run_id)):
            if v is not None:
                w.append(f"{k}=?")
                a.append(v)
        sql = "SELECT * FROM snapshots" + (" WHERE " + " AND ".join(w) if w else "") + " ORDER BY date, seq LIMIT ?"
        with self.lock:
            out = [dict(r) for r in self.con.execute(sql, a + [limit])]
        for r in out:
            for k in JSON_COLS:
                r[k] = json.loads(r[k]) if r[k] else None
        return out

    def count(self):
        with self.lock:
            return self.con.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
