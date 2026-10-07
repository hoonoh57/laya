import sys, time
import win32com.client
cp = win32com.client.Dispatch("CpUtil.CpCybos")
mgr = win32com.client.Dispatch("CpUtil.CpCodeMgr")
if cp.IsConnect != 1:
    print("Cybos 미연결"); sys.exit(1)
CODE = sys.argv[1] if len(sys.argv) > 1 else "A005930"
try:
    print("NXT 거래가능:", mgr.IsNxtTrdPsbl(CODE))
except Exception as e:
    print("IsNxtTrdPsbl 확인 불가:", e)

def fetch(kind, period, count, exch):
    ch = win32com.client.Dispatch("CpSysDib.StockChart")
    ch.SetInputValue(0, CODE); ch.SetInputValue(1, ord("2")); ch.SetInputValue(4, count)
    ch.SetInputValue(5, [0, 1, 2, 3, 4, 5, 8]); ch.SetInputValue(6, ord(kind))
    ch.SetInputValue(7, period); ch.SetInputValue(9, ord("1"))
    ch.SetInputValue(12, ord(exch)); ch.SetInputValue(13, ord("1"))
    rows, hdr = [], None
    while len(rows) < count:
        while cp.GetLimitRemainCount(1) <= 0: time.sleep(0.2)
        ch.BlockRequest()
        if ch.GetDibStatus() != 0:
            return None, ch.GetDibMsg1()
        hdr = (chr(ch.GetHeaderValue(24)) if isinstance(ch.GetHeaderValue(24), int) else ch.GetHeaderValue(24))
        n = ch.GetHeaderValue(3)
        rows += [tuple(ch.GetDataValue(f, i) for f in range(7)) for i in range(n)]
        if n == 0 or not ch.Continue: break
    return list(reversed(rows)), hdr          # 과거->최근 (정렬 금지)

def by_day(bars):
    out = {}
    for b in bars: out.setdefault(b[0], []).append(b)
    return out

print("\n[1분봉 거래소별 비교: 날짜별 봉수, 첫/끝 시각, 08시대 봉수, 거래량]")
for ex in ("K", "A", "N"):
    bars, h = fetch("m", 1, 2000, ex)
    if bars is None:
        print(f"  {ex}: 오류 {h}"); continue
    d = by_day(bars)
    for day in sorted(d)[-2:]:
        b = d[day]
        pre = sum(1 for x in b if x[1] < 900)
        print(f"  {ex}(응답={h}) {day}: 봉={len(b):>4} 첫={b[0][1]:>4} 끝={b[-1][1]:>4} 08시대={pre:>3} 거래량={sum(x[6] for x in b):>11}")

print("\n[통합(A) 40틱x3 vs 120틱 일치 검사]")
s, _ = fetch("T", 40, 15000, "A")
g, _ = fetch("T", 120, 3000, "A")
S, G = by_day(s), by_day(g)
skip = {min(S), min(G)}
today = max(S)
for day in [x for x in S if x in G and x not in skip]:
    a, b = S[day], G[day][:-1] if day == today else G[day]
    got = [(x[0][2], max(y[3] for y in x), min(y[4] for y in x), x[-1][5], sum(y[6] for y in x))
           for x in (a[i:i+3] for i in range(0, len(a), 3))][:len(b)]
    hit = sum(1 for p, q in zip(got, b) if p == q[2:])
    print(f"  {day}: 첫시각={a[0][1]:>4} 일치 {hit}/{len(b)}")
