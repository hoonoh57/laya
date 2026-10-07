import sys, time
import win32com.client
cp = win32com.client.Dispatch("CpUtil.CpCybos")
if cp.IsConnect != 1:
    print("Cybos 미연결"); sys.exit(1)
CODE = sys.argv[1] if len(sys.argv) > 1 else "A005930"

def fetch(period, count):
    ch = win32com.client.Dispatch("CpSysDib.StockChart")
    ch.SetInputValue(0, CODE); ch.SetInputValue(1, ord("2")); ch.SetInputValue(4, count)
    ch.SetInputValue(5, [0, 1, 2, 3, 4, 5, 8]); ch.SetInputValue(6, ord("T"))
    ch.SetInputValue(7, period); ch.SetInputValue(9, ord("1"))
    rows = []
    while len(rows) < count:
        while cp.GetLimitRemainCount(1) <= 0: time.sleep(0.2)
        ch.BlockRequest()
        if ch.GetDibStatus() != 0:
            print("오류:", ch.GetDibMsg1()); break
        n = ch.GetHeaderValue(3)
        rows += [tuple(ch.GetDataValue(f, i) for f in range(7)) for i in range(n)]
        if n == 0 or not ch.Continue: break
    return list(reversed(rows))               # 과거->최근 (정렬 금지)

def by_day(bars):
    out = {}
    for b in bars: out.setdefault(b[0], []).append(b)
    return out

def agg(g):
    return (g[0][2], max(x[3] for x in g), min(x[4] for x in g), g[-1][5], sum(x[6] for x in g))

small = by_day(fetch(40, 15000))
big = by_day(fetch(120, 3000))
oldest = {min(small), min(big)}               # 잘렸을 수 있는 가장 오래된 날 제외
days = [d for d in small if d in big and d not in oldest]
today = max(small)
for d in days:
    s, b = small[d], big[d]
    if d == today: b = b[:-2]                 # 진행 중인 봉 제외
    target = [x[2:] for x in b]
    print(f"\n{d}: 40틱 {len(s)}개(÷3={len(s)/3:.2f}), 120틱 비교 {len(target)}개")
    print(f"  40틱 첫 3개 시각 {[x[1] for x in s[:3]]}, 120틱 첫 시각 {b[0][1]}")
    for off in (0, 1, 2):
        groups = ([s[:off]] if off else []) + [s[i:i+3] for i in range(off, len(s), 3)]
        got = [agg(g) for g in groups][:len(target)]
        hit = sum(1 for a, t in zip(got, target) if a == t)
        first_bad = next((i for i, (a, t) in enumerate(zip(got, target)) if a != t), None)
        print(f"  offset {off}: 일치 {hit}/{len(target)}  첫 불일치 위치={first_bad}")
