"""정밀 추적 전략 (서버 64bit). 브리지 tracker 이벤트 -> ST 상승전환 -> Laya 판단 -> 스냅샷 저장.
- 추적 선정(MarketEye): 시가대비 min_open_pct~max_open_pct, track 시간대, 등락률 높은 순 max_n개
  해제: (min_open_pct - release_gap) 미만 release_sec 지속. 보유/기준진입 미청산 종목은 유지
- 판단: 확정봉(bar_close)에서만. 정규장 ST 상승전환마다 Laya 판단 + 스냅샷(학습 데이터)
- 기준 진입(하루 1회): 첫 정규장 상승전환(first_only) + entry 시간대 + 봉 기준 시가대비 범위 + p_entry>=p_min
- 결과: 다음 ST 하락전환 봉 종가 청산(features.outcome) -> 스냅샷 outcome 갱신
- 주문 없음(그림자 기록). 매도 로직(JMA+Laya)은 이후 단계"""
import asyncio
import logging
import time
from pathlib import Path

from . import features as F
from . import ta
from .config import ROOT
from .laya_judge import Judge, SnapStore

log = logging.getLogger("strategy")

DEFAULTS = {
    "enabled": False,
    "kind": "T", "period": 360,
    "min_open_pct": 2.0, "max_open_pct": 20.0,
    "track_start": "09:00", "track_end": "15:20",
    "entry_start": "09:00", "entry_end": "10:30",
    "release_gap": 1.0, "release_sec": 30,
    "max_n": 20, "p_min": 0.6,
    "first_only": True,
}


def _hm(t):
    t = int(t)
    return "%02d:%02d" % (t // 100, t % 100)


class Book:
    """종목별 확정봉 + 지표 + 판단 대기 목록"""

    def __init__(self, code, name, bars):
        self.code, self.name = code, name or ""
        self.bars = [b for b in bars if not b.get("live")]
        self.ind = ta.compute(self.bars)
        self.pending = []          # 결과 대기 판단 {"sid","date","seq","t","entry"}
        self.entry = None          # 기준 진입 {"sid","date","seq","t","price","closed"}
        self.live = None

    def last_key(self):
        if not self.bars:
            return None
        b = self.bars[-1]
        return (b["date"], b["seq"])

    def add(self, bar):
        """반환: 새 idx / None = 중복 / -1 = 끊김(다시 받기 필요)"""
        k, key = self.last_key(), (bar["date"], bar["seq"])
        if k is not None:
            if key <= k:
                return None
            if (bar["date"] == k[0] and bar["seq"] != k[1] + 1) or (bar["date"] != k[0] and bar["seq"] != 0):
                return -1
        self.bars.append(dict(bar, live=False))
        self.ind = ta.compute(self.bars)
        return len(self.bars) - 1


class Strategy:
    def __init__(self, eng, store_path=None):
        self.eng = eng
        self.store_path = Path(store_path) if store_path else ROOT / "data" / "snapshots.db"
        self.store = self.judge = None
        self.books, self.sent = {}, None
        self.below, self.chg, self.names, self.peers, self.bad = {}, {}, {}, [], {}
        self.q = self.worker = self.lock = None
        self.run_id = "live-" + time.strftime("%Y%m%d")
        self.stats = {"closes": 0, "judged": 0, "entries": 0, "resync": 0, "errors": 0}
        self.last_err = None

    def cfg(self):
        return {**DEFAULTS, **(self.eng.cfg.get("track") or {})}

    async def emit(self, kind, data, store=True):
        try:
            await self.eng.hub.emit(kind, data, store=store)
        except Exception:  # noqa: BLE001
            log.exception("emit")

    def protected(self):
        held = {h.get("code") for h in ((self.eng.account or {}).get("holdings") or [])}
        held |= {c for c, b in self.books.items() if b.entry and not b.entry.get("closed")}
        return held

    # ---------- 추적 선정 (순수 함수: 테스트 가능) ----------
    def select(self, rows, now=None, hm=None):
        c = self.cfg()
        now = time.time() if now is None else now
        hm = hm or time.strftime("%H:%M")
        on = bool(c["enabled"]) and c["track_start"] <= hm < c["track_end"]
        q = {}
        for r in rows or []:
            o, p = r.get("open") or 0, r.get("price") or 0
            if o > 0 and p > 0:
                q[r["code"]] = (p / o - 1) * 100
        self.chg = q
        keep, lo, out = self.protected(), c["min_open_pct"] - c["release_gap"], []
        for code in self.sent or []:
            if code in keep:
                out.append(code)
                continue
            if not on:
                continue
            x = q.get(code)
            if x is not None and x < lo:
                t0 = self.below.setdefault(code, now)
                if now - t0 >= c["release_sec"]:
                    self.below.pop(code, None)
                    continue
            else:
                self.below.pop(code, None)
            out.append(code)
        if on:
            cands = sorted((x, code) for code, x in q.items()
                           if code not in out and self.bad.get(code, 0) <= now
                           and c["min_open_pct"] <= x <= c["max_open_pct"])
            for x, code in reversed(cands):
                if len(out) >= int(c["max_n"]):
                    break
                out.append(code)
        return out

    # ---------- 브리지 동기화 ----------
    def reset_bridge(self):
        """브리지 재연결 시 호출: 브리지 추적 상태가 사라졌으므로 다시 보냄"""
        self.sent = None
        self.books.clear()

    async def sync(self, rows):
        self.peers = rows or []
        for r in self.peers:
            if r.get("name"):
                self.names[r["code"]] = r["name"]
        if self.lock is None:
            self.lock = asyncio.Lock()
        if self.lock.locked():
            return
        async with self.lock:
            want = self.select(rows)
            if self.sent is not None and set(want) == set(self.sent):
                return
            if self.sent is None and not want:
                self.sent = []
                return
            c = self.cfg()
            r = await self.eng.cybos.call("track_set", timeout=180, codes=want, kind=c["kind"],
                                          period=int(c["period"]), min_ok=300)
            self.sent = list(r.get("tracking") or [])
            for code in list(self.books):
                if code not in self.sent:
                    self.books.pop(code, None)
            for code in r.get("added") or []:
                await self._load(code)
            if r.get("errors"):
                for code in r["errors"]:
                    self.bad[code] = time.time() + 300
                await self.emit("log", {"level": "error", "msg": f"추적 시작 실패(5분 후 재시도): {r['errors']}"})
            await self.emit("track", self.snapshot(), store=False)

    async def _load(self, code):
        r = await self.eng.cybos.call("track_bars", timeout=60, code=code)
        old = self.books.get(code)
        bk = Book(code, self.names.get(code, ""), r["bars"])
        if old:
            bk.entry, bk.pending = old.entry, old.pending
        self.books[code] = bk

    # ---------- 브리지 이벤트 ----------
    async def on_event(self, msg):
        ev, d = msg.get("event"), msg.get("data") or {}
        if ev == "bar_live":
            bk = self.books.get(d.get("code"))
            if bk:
                bk.live = d.get("bar")
            await self.emit("bar_live", d, store=False)
        elif ev in ("bar_close", "track_reset"):
            if self.q is None:
                self.q = asyncio.Queue()
                self.worker = asyncio.create_task(self._work())
            self.q.put_nowait((ev, d))

    async def _work(self):
        while True:
            ev, d = await self.q.get()
            try:
                if ev == "bar_close":
                    await self.handle_close(d["code"], d["bar"])
                elif d.get("code") in self.books:
                    await self._load(d["code"])
            except Exception as e:  # noqa: BLE001
                self.stats["errors"] += 1
                self.last_err = f"{type(e).__name__}: {e}"
                log.exception("strategy")

    async def handle_close(self, code, bar):
        bk = self.books.get(code)
        if bk is None:
            return
        i = bk.add(bar)
        if i is None:
            return
        if i == -1:
            self.stats["resync"] += 1
            await self._load(code)
            bk = self.books[code]
            i = len(bk.bars) - 1
            if i < 0 or (bk.bars[i]["date"], bk.bars[i]["seq"]) != (bar["date"], bar["seq"]):
                return
        self.stats["closes"] += 1
        st, jm = bk.ind["st"][i], bk.ind["jma"][i]
        c = self.cfg()
        await self.emit("bar_close", {"code": code, "kind": c["kind"], "period": c["period"],
                                      "bar": bk.bars[i], "st": st, "jma": jm}, store=False)
        if st is None:
            return
        if st["turn"] == -1:
            await self._close_pending(bk)
        elif st["turn"] == 1 and bk.bars[i]["session"] == "reg":
            await self._judge(bk, i)

    async def _judge(self, bk, i):
        c = self.cfg()
        if self.eng.gate is None:
            await self.emit("log", {"level": "error", "msg": f"{bk.code} 상승전환 - Laya 로딩 전이라 판단 생략"})
            return
        if self.judge is None:
            self.judge = Judge(self.eng.gate)
        if self.store is None:
            self.store = SnapStore(self.store_path)
        ob = (getattr(self.eng, "orderbooks", None) or {}).get(bk.code)
        snap = F.build(bk.code, bk.name, c["kind"], int(c["period"]), bk.bars, bk.ind, i, ob=ob, peers=self.peers)
        j = await asyncio.to_thread(self.judge, snap["state"])
        f = snap["f"]
        x = f.get("chg_open_pct")
        checks = [
            ("첫 상승전환 아님", f["ups_today"] == 1 or not c["first_only"]),
            ("진입 시간대 밖", c["entry_start"] <= _hm(f["t"]) < c["entry_end"]),
            ("시가대비 범위 밖", x is not None and c["min_open_pct"] <= x <= c["max_open_pct"]),
            ("p_entry 미달", j["p_entry"] >= c["p_min"]),
            ("오늘 이미 진입", bk.entry is None or bk.entry["date"] != f["date"]),
        ]
        why = [n for n, ok in checks if not ok]
        entry = not why
        sid = self.store.save("live", self.run_id, snap, j, entry)
        self.stats["judged"] += 1
        bk.pending.append({"sid": sid, "date": f["date"], "seq": f["seq"], "t": f["t"], "entry": entry})
        if entry:
            self.stats["entries"] += 1
            bk.entry = {"sid": sid, "date": f["date"], "seq": f["seq"], "t": f["t"], "price": f["close"], "closed": None}
        await self.emit("signal", {
            "code": bk.code, "name": bk.name, "date": f["date"], "seq": f["seq"], "t": f["t"], "close": f["close"],
            "chg_open_pct": x, "ups_today": f["ups_today"], "p_entry": j["p_entry"], "quality": j["quality"],
            "basis": j["basis"], "regime": j["regime"], "latency_ms": j["latency_ms"],
            "entry": entry, "why": why, "sid": sid, "shadow": True})

    async def _close_pending(self, bk):
        if not bk.pending:
            return
        idx = {(b["date"], b["seq"]): k for k, b in enumerate(bk.bars)}
        for p in bk.pending:
            k = idx.get((p["date"], p["seq"]))
            if k is None:
                continue
            o = F.outcome(bk.bars, bk.ind, k)
            if self.store:
                self.store.set_outcome(p["sid"], o)
            if p["entry"] and bk.entry and bk.entry["sid"] == p["sid"]:
                bk.entry["closed"] = o
            await self.emit("signal_outcome", {"code": bk.code, "name": bk.name, "sid": p["sid"],
                                               "entry": p["entry"], "t": p["t"], **o})
        bk.pending = []

    # ---------- 조회 ----------
    def snapshot(self):
        items = {}
        for code in self.sent or []:
            bk, x = self.books.get(code), self.chg.get(code)
            it = {"name": self.names.get(code, ""), "chg_open": round(x, 2) if x is not None else None}
            if bk and bk.bars:
                i = len(bk.bars) - 1
                s = bk.ind["st"][i]
                it.update(bars=len(bk.bars), t=bk.bars[i]["t"], seq=bk.bars[i]["seq"],
                          st_up=s["up"] if s else None, entry=bk.entry, pending=len(bk.pending))
            items[code] = it
        return {"cfg": self.cfg(), "tracking": list(self.sent or []), "stats": self.stats,
                "last_err": self.last_err, "items": items}
