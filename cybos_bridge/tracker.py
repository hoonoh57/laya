"""정밀 추적 (32bit 브리지 내부, COM 메인 스레드에서만 호출).
- 실시간 체결: NXT 거래가능 -> Dscbo1.StockBsccnsCnld(통합 KRX+NXT), KRX 전용 -> Dscbo1.StockCur
  (실측: 정규장 실시간 체결 약 1/3 누락 -> 실시간은 잠정봉 표시용)
- 잠정봉 bar_live: 현재가/고가/저가 = 실시간, 거래량 = 누적거래량[9] - 오늘 확정봉 거래량 합
- 확정봉 bar_close: ChartPager.refresh() = StockChart 원본. ST 판정/Laya/스냅샷은 확정봉만 사용
- 재조회 조건(체결이 들어온 종목만, 직전 조회 후 poll초 이상):
  통계 있음: 봉당 수신체결 75% 도달 또는 평균 봉간격 1.2배 경과 / 통계 없음: 봉간격 추정치 70% 경과
  남은 시세조회 한도 < reserve 이면 미룸(MarketEye/호가 몫 보호). 한 번에 1종목만 조회."""
import time

import win32com.client

from chart_std import ChartPager, is_open

RT_NXT, RT_KRX = "Dscbo1.StockBsccnsCnld", "Dscbo1.StockCur"


def plain(c):
    c = str(c).strip()
    if len(c) == 7 and c[0].isalpha():
        c = c[1:]
    return c.zfill(6) if c.isdigit() else c


def acode(c):
    c = str(c).strip()
    if c[:1].isalpha():
        return c
    return "A" + (c.zfill(6) if c.isdigit() else c)


def today():
    lt = time.localtime()
    return lt.tm_year * 10000 + lt.tm_mon * 100 + lt.tm_mday


def avg(xs):
    return sum(xs) / len(xs) if xs else None


def median(xs):
    if not xs:
        return None
    s = sorted(xs)
    return s[len(s) // 2]


def mins(t):
    return (t // 100) * 60 + t % 100


class TickHandler:
    def init(self, tr, code, obj):
        self.tr, self.code, self.obj = tr, code, obj

    def OnReceived(self):
        try:
            self.tr.on_tick(self.code, self.obj)
        except Exception as e:  # noqa: BLE001
            self.tr.log("tick error", self.code, repr(e))


class Item:
    def __init__(self, code, name, pager, rt):
        self.code, self.name, self.pager, self.rt = code, name, pager, rt
        self.obj = self.handler = None
        self.last_key = None              # 마지막 확정봉 (date, seq)
        self.day_vol = 0                  # 오늘 확정봉 거래량 합
        self.live = None                  # 잠정봉
        self.live_dirty, self.live_sent = False, 0.0
        self.ticks = self.ticks_refresh = self.ticks_bar = 0
        self.cum = None                   # 최근 누적거래량[9]
        self.iv, self.tpb = [], []        # 최근 봉 간격(초), 봉당 수신 체결 수
        self.iv_seed = None
        self.last_confirm = time.time()
        self.next_ok = 0.0
        self.calls = self.fails = self.resets = self.confirmed = 0
        self.lat, self.vol_gap = [], []

    def due_at(self, poll):
        a = avg(self.iv) or self.iv_seed
        return self.last_confirm + (0.7 * a if a else poll)

    def due(self, now, poll):
        if self.ticks_refresh <= 0 or now < self.next_ok:
            return False
        t, a = avg(self.tpb), avg(self.iv)
        if t and a:
            return self.ticks_bar >= 0.75 * t or now >= self.last_confirm + 1.2 * a
        return now >= self.due_at(poll)


class Tracker:
    def __init__(self, cp, codemgr, emit, log, poll=2.5, reserve=12, live_gap=0.5, max_n=20):
        self.cp, self.codemgr, self.emit_raw, self.log = cp, codemgr, emit, log
        self.poll, self.reserve, self.live_gap, self.max_n = poll, reserve, live_gap, max_n
        self.kind, self.period, self.min_ok = "T", 360, 300
        self.items = {}
        self.deferred = 0

    def emit(self, ev, data):
        self.emit_raw({"event": ev, "data": data})

    # ---------- 종목 관리 ----------
    def set(self, codes, kind="T", period=360, min_ok=300):
        want = []
        for c in codes:
            c = plain(c)
            if c and c not in want:
                want.append(c)
        want = want[: self.max_n]
        if (kind, int(period)) != (self.kind, self.period):
            self.clear()
            self.kind, self.period = kind, int(period)
        self.min_ok = int(min_ok)
        removed = [c for c in list(self.items) if c not in want]
        for c in removed:
            self._drop(c)
        added, errors = [], {}
        for c in want:
            if c in self.items:
                continue
            try:
                self._add(c)
                added.append(c)
            except Exception as e:  # noqa: BLE001
                errors[c] = f"{type(e).__name__}: {e}"
        return {"tracking": list(self.items), "added": added, "removed": removed, "errors": errors,
                "kind": self.kind, "period": self.period}

    def _pager(self, code):
        p = ChartPager(self.cp, acode(code), self.kind, self.period)
        p.ensure(self.min_ok)
        return p

    def _add(self, code):
        name = self.codemgr.CodeToName(acode(code))
        if not name:
            raise ValueError(f"유효하지 않은 종목코드: {code}")
        rt = RT_NXT if self.codemgr.IsNxtTrdPsbl(acode(code)) else RT_KRX
        it = Item(code, name, self._pager(code), rt)
        self._sync(it, emit=False)
        o = win32com.client.Dispatch(rt)
        h = win32com.client.WithEvents(o, TickHandler)
        h.init(self, code, o)
        o.SetInputValue(0, acode(code))
        o.Subscribe()
        it.obj, it.handler = o, h
        self.items[code] = it

    def _drop(self, code):
        it = self.items.pop(code, None)
        if it and it.obj is not None:
            try:
                it.obj.Unsubscribe()
            except Exception:  # noqa: BLE001
                pass

    def clear(self):
        for c in list(self.items):
            self._drop(c)

    # ---------- 확정봉 동기화 ----------
    def _sync(self, it, emit):
        bs = it.pager.bars()
        d = today()
        done = [b for b in bs if not b["live"]]
        td = [b for b in done if b["date"] == d]
        it.day_vol = sum(b["v"] for b in td)
        if it.iv_seed is None and len(td) >= 6:          # 시작 직후 봉 간격 추정 (hhmm 해상도)
            w = td[-11:]
            span = mins(w[-1]["t"]) - mins(w[0]["t"])
            if span >= 2:
                it.iv_seed = span * 60 / (len(w) - 1)
        new = [b for b in done if it.last_key is None or (b["date"], b["seq"]) > it.last_key]
        if done:
            it.last_key = (done[-1]["date"], done[-1]["seq"])
        if emit:
            for b in new:
                self.emit("bar_close", {"code": it.code, "kind": self.kind, "period": self.period, "bar": b})
        lb = bs[-1] if bs and bs[-1]["live"] else None
        if emit and it.cum:                              # 실시간 [9] vs 차트 누적(확정 + 진행봉)
            it.vol_gap = (it.vol_gap + [it.cum - it.day_vol - (lb["v"] if lb else 0)])[-50:]
        it.live = dict(lb, provisional=True, ticks_rt=0) if lb else None
        it.live_dirty = lb is not None
        return len(new)

    # ---------- 실시간 체결 ----------
    def on_tick(self, code, obj):
        it = self.items.get(code)
        if it is None:
            return
        price = obj.GetHeaderValue(13)
        if not price:
            return
        cum = obj.GetHeaderValue(9)
        it.ticks += 1
        it.ticks_refresh += 1
        it.ticks_bar += 1
        it.cum = cum
        lv = it.live
        if lv is None:
            d = today()
            seq = it.last_key[1] + 1 if it.last_key and it.last_key[0] == d else 0
            lv = it.live = {"date": d, "seq": seq, "t": obj.GetHeaderValue(18) // 100,
                            "o": price, "h": price, "l": price, "c": price, "v": 0, "parts": 0,
                            "live": True, "provisional": True, "ticks_rt": 0}
        lv["h"] = max(lv["h"], price)
        lv["l"] = min(lv["l"], price)
        lv["c"] = price
        if cum:
            lv["v"] = max(0, cum - it.day_vol)
        lv["ticks_rt"] += 1
        it.live_dirty = True

    # ---------- 메인 루프에서 매번 호출 ----------
    def tick(self):
        now = time.time()
        for it in self.items.values():
            if it.live_dirty and it.live and now - it.live_sent >= self.live_gap:
                it.live_dirty, it.live_sent = False, now
                self.emit("bar_live", {"code": it.code, "kind": self.kind, "period": self.period, "bar": it.live})
        if not self.items or not is_open(today()):
            return
        cands = [it for it in self.items.values() if it.due(now, self.poll)]
        if not cands:
            return
        if self.cp.GetLimitRemainCount(1) < self.reserve:
            self.deferred += 1
            return
        self._refresh(min(cands, key=lambda x: x.due_at(self.poll)))

    def _refresh(self, it):
        a = time.perf_counter()
        try:
            r = it.pager.refresh()
        except Exception as e:  # noqa: BLE001
            it.fails += 1
            it.next_ok = time.time() + self.poll
            self.log("refresh error", it.code, repr(e))
            return
        it.calls += 1
        it.lat = (it.lat + [(time.perf_counter() - a) * 1000])[-50:]
        it.ticks_refresh = 0
        if r < 0:
            it.resets += 1
            self.log("겹침 실패 -> 다시 받기", it.code)
            it.pager = self._pager(it.code)
            self.emit("track_reset", {"code": it.code})
        n = self._sync(it, emit=True)
        now = time.time()
        if n:
            if it.confirmed:                      # 첫 확정은 시작 시점 영향 -> 통계 제외
                it.iv = (it.iv + [(now - it.last_confirm) / n])[-5:]
                it.tpb = (it.tpb + [it.ticks_bar / n])[-5:]
            it.ticks_bar = 0
            it.last_confirm = now
            it.confirmed += n
        it.next_ok = now + self.poll

    # ---------- 조회 ----------
    def status(self):
        out = {}
        for c, it in self.items.items():
            out[c] = {"name": it.name, "rt": it.rt.split(".")[-1], "confirmed": it.confirmed,
                      "calls": it.calls, "fails": it.fails, "resets": it.resets, "ticks": it.ticks,
                      "iv_seed": round(it.iv_seed, 1) if it.iv_seed else None,
                      "avg_iv": round(avg(it.iv), 1) if it.iv else None,
                      "tpb": round(avg(it.tpb), 1) if it.tpb else None,
                      "lat_avg": round(avg(it.lat)) if it.lat else None,
                      "lat_max": round(max(it.lat)) if it.lat else None,
                      "vol_gap_med": median(it.vol_gap), "last": it.last_key, "live": it.live}
        return {"kind": self.kind, "period": self.period, "poll": self.poll, "reserve": self.reserve,
                "limit_remain": self.cp.GetLimitRemainCount(1), "deferred": self.deferred, "items": out}

    def bars(self, code):
        it = self.items.get(plain(code))
        if it is None:
            raise ValueError(f"추적 중 아님: {code}")
        return {"code": it.code, "kind": self.kind, "period": self.period,
                "bars": it.pager.bars(), "live": it.live}
