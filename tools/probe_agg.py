import sys, time
import win32com.client
cp = win32com.client.Dispatch("CpUtil.CpCybos")
if cp.IsConnect != 1:
    print("Cybos 미연결"); sys.exit(1)
CODE = sys.argv[1] if len(sys.argv) > 1 else "A005930"
N = int(sys.argv[2]) if len(sys.argv) > 2 else 3          # 120틱 x N = 360틱

ch = win32com.client.Dispatch("CpSysDib.StockChart")
ch.SetInputValue(0, CODE); ch.SetInputValue(1, ord("2")); ch.SetInputValue(4, 3000)
ch.SetInputValue(5, [0, 1, 2, 3, 4, 5, 8]); ch.SetInputValue(6, ord("T"))
ch.SetInputValue(7, 120); ch.SetInputValue(9, ord("1"))
while cp.GetLimitRemainCount(1) <= 0: time.sleep(0.2)
ch.BlockRequest()
n = ch.GetHeaderValue(3)
raw = [tuple(ch.GetDataValue(f, i) for f in range(7)) for i in range(n)]
bars = list(reversed(raw))                    # 과거->최근 (정렬 금지)

def agg(g):
    return (g[0][0], g[0][1], g[-1][1], g[0][2], max(b[3] for b in g),
            min(b[4] for b in g), g[-1][5], sum(b[6] for b in g), len(g))

days = []
for b in bars:
    if not days or days[-1][0][0] != b[0]: days.append([])
    days[-1].append(b)
days = days[1:]                                # 가장 오래된 날은 잘렸을 수 있음
A = [agg(d[i:i+N]) for d in days for i in range(0, len(d), N)]
flat = [b for d in days for b in d]
B = [agg(flat[i:i+N]) for i in range(0, len(flat), N)]

hdr = "  날짜      첫봉 끝봉   시가    고가    저가    종가     거래량  구성"
for name, xs in (("A안 날마다 새로", A), ("B안 이어서", B)):
    print(f"\n=== {name}  {120*N}틱  (120틱봉 {len(flat)}개, 날짜별 개수 {[len(d) for d in days]})")
    print(hdr)
    last_day = xs[-1][0]
    today = [x for x in xs if x[0] == last_day]
    prev = [x for x in xs if x[0] != last_day]
    for x in prev[-2:] + today[:3] + today[-5:]:
        print("  {} {:>4} {:>4} {:>7} {:>7} {:>7} {:>7} {:>10} {:>3}".format(*x))
