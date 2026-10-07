"""Cybos StockChart 표준화 (32bit). 측정으로 확정된 규칙:
- 거래소 12='A'(통합=KRX+NXT, 거래량 합계 일치 확인), 13='1'(KRX 애프터 포함)
- 응답은 최근순 -> reverse만 사용 (hhmm 해상도라 sort 금지), 날짜별 seq 부여
- 틱 주기 상한 120 -> 초과 주기는 base 틱봉을 '날짜별 첫 봉부터' N개씩 묶음 (Cybos 원본과 100% 일치)
- 분봉 시각은 끝시각 표기 -> 시작시각(t)으로 변환, 원본은 t_raw. 틱봉은 원본 유지
- 세션: pre 08:00~08:49 / gap 08:50~08:59 / reg 09:00~15:19 / close 15:20~15:39
        after_nxt 15:40~15:59(NXT만) / after 16:00~20:00
"""
import time
import win32com.client

FIELDS = [0, 1, 2, 3, 4, 5, 8, 9]          # 날짜, 시간, 시가, 고가, 저가, 종가, 거래량, 거래대금
TICK_MAX = 120


def hhmm_sub(t, m):
    x = (t // 100) * 60 + t % 100 - m
    return (x // 60) * 100 + x % 60


def session(t):
    if t < 850: return "pre"
    if t < 900: return "gap"
    if t < 1520: return "reg"
    if t < 1540: return "close"
    if t < 1600: return "after_nxt"
    return "after"


def is_open(date):
    """오늘이고 20:00(NXT 애프터 종료) 이전일 때만 진행 중 봉이 존재"""
    lt = time.localtime()
    today = lt.tm_year * 10000 + lt.tm_mon * 100 + lt.tm_mday
    return date == today and lt.tm_hour * 100 + lt.tm_min < 2000


class ChartPager:
    def __init__(self, cp, code, kind, period, exch="A", page=2000):
        self.cp, self.code, self.kind, self.period = cp, code, kind, period
        self.exch, self.page = exch, page
        if kind == "T" and period > TICK_MAX:
            self.base = max(d for d in range(1, TICK_MAX + 1) if period % d == 0)
        else:
            self.base = period
        self.n = period // self.base
        self.obj = None
        self.raw = []                        # base 봉, 과거->최근
        self.has_prev = True
        self.pages = 0

    def _make(self):
        ch = win32com.client.Dispatch("CpSysDib.StockChart")
        ch.SetInputValue(0, self.code); ch.SetInputValue(1, ord("2"))
        ch.SetInputValue(4, self.page); ch.SetInputValue(5, FIELDS)
        ch.SetInputValue(6, ord(self.kind)); ch.SetInputValue(7, self.base)
        ch.SetInputValue(9, ord("1"))
        ch.SetInputValue(12, ord(self.exch)); ch.SetInputValue(13, ord("1"))
        return ch

    def load_page(self):
        """첫 호출은 최신 페이지, 이후 호출은 이전 페이지. 반환: 받은 base 봉 수"""
        if self.obj is None:
            self.obj = self._make()
        elif not self.has_prev:
            return 0
        while self.cp.GetLimitRemainCount(1) <= 0:
            time.sleep(0.2)
        self.obj.BlockRequest()
        if self.obj.GetDibStatus() != 0:
            raise RuntimeError(self.obj.GetDibMsg1())
        cnt = self.obj.GetHeaderValue(3)
        rows = [tuple(self.obj.GetDataValue(f, i) for f in range(len(FIELDS))) for i in range(cnt)]
        rows.reverse()
        self.raw = rows + self.raw
        self.has_prev = bool(cnt) and bool(self.obj.Continue)
        self.pages += 1
        return cnt

    def ensure(self, min_ok, max_pages=40):
        """완전한 날짜의 봉(day_ok)이 min_ok개 이상 될 때까지 이전 페이지 자동 수신"""
        while self.pages < max_pages:
            if self.pages and sum(1 for b in self.bars() if b["day_ok"]) >= min_ok:
                return True
            if self.pages and not self.has_prev:
                return False
            self.load_page()
        return False

    def bars(self):
        days = []
        for r in self.raw:
            if not days or days[-1][0][0] != r[0]:
                days.append([])
            days[-1].append(r)
        out = []
        last_date = days[-1][0][0] if days else None
        for di, d in enumerate(days):
            day_ok = di > 0                  # 가장 오래된 날은 앞부분이 잘렸을 수 있음
            groups = [d[i:i + self.n] for i in range(0, len(d), self.n)]
            for s, g in enumerate(groups):
                t_raw, te_raw = g[0][1], g[-1][1]
                if self.kind == "m":
                    t, te = hhmm_sub(t_raw, self.period), hhmm_sub(te_raw, self.period)
                else:
                    t, te = t_raw, te_raw
                s0, s1 = session(t), session(te)
                out.append({
                    "date": g[0][0], "seq": s, "t": t, "t_raw": t_raw, "t_end_raw": te_raw,
                    "o": g[0][2], "h": max(x[3] for x in g), "l": min(x[4] for x in g),
                    "c": g[-1][5], "v": sum(x[6] for x in g), "amt": sum(x[7] for x in g),
                    "parts": len(g), "session": s0, "mixed": s0 != s1,
                    "day_ok": day_ok, "day_last": s == len(groups) - 1,
                    "live": g[0][0] == last_date and s == len(groups) - 1 and is_open(g[0][0]),
                })
        return out
