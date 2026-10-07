import sys
from collections import Counter
sys.path.insert(0, r"E:\2026\laya\cybos_bridge")
import win32com.client
from chart_std import ChartPager
cp = win32com.client.Dispatch("CpUtil.CpCybos")
if cp.IsConnect != 1:
    print("Cybos 미연결"); sys.exit(1)
CODE = sys.argv[1] if len(sys.argv) > 1 else "A005930"

p = ChartPager(cp, CODE, "T", 360)
ok = p.ensure(300)
bs = p.bars()
print(f"[360틱 ensure(300)] 성공={ok} 페이지={p.pages} 완전봉={sum(b['day_ok'] for b in bs)} 전체={len(bs)}")
for d in sorted({b['date'] for b in bs}):
    x = [b for b in bs if b["date"] == d]
    c = Counter(b["session"] for b in x)
    print(f"  {d} ok={x[0]['day_ok']} 봉={len(x):>4} 세션={dict(c)} 경계걸침={sum(b['mixed'] for b in x)}")
mixed = [b for b in bs if b["mixed"] and b["day_ok"]]
for b in mixed[:6]:
    print(f"   걸침: {b['date']} seq={b['seq']} {b['t_raw']}~{b['t_end_raw']} {b['session']} V={b['v']}")

m = ChartPager(cp, CODE, "m", 1)
m.ensure(700)
mb = [b for b in m.bars() if b["day_ok"]]
d = mb[-1]["date"] if mb[-1]["live"] is False else sorted({b['date'] for b in mb})[-2]
x = [b for b in mb if b["date"] == d]
print(f"\n[1분봉 {d}] {len(x)}개 세션={dict(Counter(b['session'] for b in x))}")
for b in x:
    if b["t"] in (849, 900, 1519, 1530, 1540, 1559, 1600):
        print(f"   t={b['t']:>4} raw={b['t_raw']:>4} {b['session']:<9} O={b['o']} C={b['c']} V={b['v']}")
