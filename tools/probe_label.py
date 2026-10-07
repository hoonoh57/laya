import sys, time
import win32com.client
cp = win32com.client.Dispatch("CpUtil.CpCybos")
if cp.IsConnect != 1:
    print("Cybos 미연결"); sys.exit(1)
CODE = sys.argv[1] if len(sys.argv) > 1 else "A005930"

def fetch(kind, period, count):
    ch = win32com.client.Dispatch("CpSysDib.StockChart")
    ch.SetInputValue(0, CODE); ch.SetInputValue(1, ord("2")); ch.SetInputValue(4, count)
    ch.SetInputValue(5, [0, 1, 2, 5, 8]); ch.SetInputValue(6, ord(kind))
    ch.SetInputValue(7, period); ch.SetInputValue(9, ord("1"))
    rows = []
    while len(rows) < count:
        while cp.GetLimitRemainCount(1) <= 0: time.sleep(0.2)
        ch.BlockRequest()
        n = ch.GetHeaderValue(3)
        rows += [tuple(ch.GetDataValue(f, i) for f in range(5)) for i in range(n)]
        if n == 0 or not ch.Continue: break
    return rows                      # 받은 순서 그대로 (정렬 금지)

for kind, period, count, name in [("m", 1, 900, "1분봉"), ("T", 60, 3000, "60틱")]:
    raw = fetch(kind, period, count)
    print(f"\n=== {name}: {len(raw)}개, 받은순서 첫={raw[0][:2]} 끝={raw[-1][:2]}")
    chron = list(reversed(raw))
    dates = []
    for r in chron:
        if not dates or dates[-1] != r[0]: dates.append(r[0])
    day = dates[-2] if len(dates) >= 2 else dates[-1]
    d = [r for r in chron if r[0] == day]
    print(f"기준일 {day}: {len(d)}개  (날짜, hhmm, 시가, 종가, 거래량)")
    for r in d[:4]: print("  첫", r)
    for r in d[-6:]: print("  끝", r)
