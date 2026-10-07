import sys, time
import win32com.client

cp = win32com.client.Dispatch("CpUtil.CpCybos")
if cp.IsConnect != 1:
    print("Cybos 미연결"); sys.exit(1)

CODE = sys.argv[1] if len(sys.argv) > 1 else "A005930"
PERIODS = [1, 10, 15, 30, 60, 120, 180, 240, 360, 480, 720]
COUNT = 3000

def fetch(period):
    ch = win32com.client.Dispatch("CpSysDib.StockChart")
    ch.SetInputValue(0, CODE)
    ch.SetInputValue(1, ord("2"))          # 개수 요청
    ch.SetInputValue(4, COUNT)
    ch.SetInputValue(5, [0, 1, 5, 8])      # 날짜, 시간, 종가, 거래량
    ch.SetInputValue(6, ord("T"))          # 틱
    ch.SetInputValue(7, period)
    ch.SetInputValue(9, ord("1"))          # 수정주가
    rows, calls = [], 0
    while len(rows) < COUNT:
        while cp.GetLimitRemainCount(1) <= 0:
            time.sleep(0.2)
        ch.BlockRequest(); calls += 1
        if ch.GetDibStatus() != 0:
            return None, ch.GetDibMsg1(), calls
        n = ch.GetHeaderValue(3)
        rows += [(ch.GetDataValue(0, i), ch.GetDataValue(1, i), ch.GetDataValue(3, i)) for i in range(n)]
        if n == 0 or not ch.Continue:
            break
    return rows, "", calls                 # 받은 순서 그대로 (정렬 금지)

data, info = {}, {}
for p in PERIODS:
    rows, err, calls = fetch(p)
    if rows is None:
        print(f"{p:>4}틱  오류: {err}"); continue
    data[p] = rows
    seen = []
    for r in reversed(rows):
        if not seen or seen[-1] != r[0]: seen.append(r[0])
    day = seen[-2] if len(seen) >= 3 else seen[-1]   # 잘리지 않은 직전 거래일
    nday = sum(1 for r in rows if r[0] == day)
    vol = sum(r[2] for r in rows if r[0] == day)
    info[p] = (day, nday)
    sig = [r[:2] for r in rows]
    same = [q for q in data if q != p and [r[:2] for r in data[q]] == sig]
    print(f"{p:>4}틱  봉={len(rows):>5} 호출={calls:>2} 받은순서 첫={rows[0][:2]} 끝={rows[-1][:2]} "
          f"기준일={day} 봉수={nday:>5} 거래량={vol:>12}" + (f"  <- {same}틱과 동일(미지원 의심)" if same else ""))

if 60 in info and info[60][1]:
    bday, bn = info[60]
    print(f"\n[기준일 {bday}, 60틱 봉수 기준 예상/실제]")
    for p in PERIODS:
        if p in info and info[p][0] == bday:
            print(f"{p:>4}틱  예상~{bn*60/p:>8.1f}  실제={info[p][1]:>6}")
