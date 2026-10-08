"""실시간 체결(StockBsccnsCnld) vs StockChart 1틱(통합 A) 분 단위 비교 -> 체결 누락률 측정.
python probe_rt3.py <종목> <초>"""
import sys
import time
from collections import Counter
from pathlib import Path

import pythoncom
import win32com.client

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cybos_bridge"))
from chart_std import ChartPager  # noqa: E402

code = sys.argv[1] if len(sys.argv) > 1 else "A005930"
secs = int(sys.argv[2]) if len(sys.argv) > 2 else 120
cp = win32com.client.Dispatch("CpUtil.CpCybos")
if not cp.IsConnect:
    sys.exit("Cybos 미연결 (관리자 권한 콘솔에서 실행)")
ev = []


class H:
    def init(self, obj):
        self.obj = obj

    def OnReceived(self):
        g = self.obj.GetHeaderValue
        x = g(29)
        ev.append((int(g(18)), int(g(13)), int(g(17)), int(g(9)), chr(x) if isinstance(x, int) else str(x)))


o = win32com.client.Dispatch("Dscbo1.StockBsccnsCnld")
h = win32com.client.WithEvents(o, H)
h.init(o)
o.SetInputValue(0, code)
o.Subscribe()
print(f"{code} 통합 실시간 {secs}초 수신 시작 {time.strftime('%H:%M:%S')}")
end = time.time() + secs
while time.time() < end:
    pythoncom.PumpWaitingMessages()
    time.sleep(0.003)
o.Unsubscribe()
if len(ev) < 2:
    sys.exit(f"수신 {len(ev)}건 - 비교 불가")

rt_n, rt_v, rt_x = Counter(), Counter(), {}
for s, p, q, cv, x in ev:
    m = s // 100
    rt_n[m] += 1
    rt_v[m] += q
    rt_x.setdefault(m, Counter())[x] += 1
mins = sorted(rt_n)[1:-1]           # 처음/마지막 분은 일부만 받았으므로 제외
if not mins:
    sys.exit("완전한 분이 없음 - 초를 늘려 다시 실행")

today = int(time.strftime("%Y%m%d"))
p = ChartPager(cp, code, "T", 1)
p.load_page()
while p.has_prev and p.pages < 15 and min(b["t"] for b in p.bars() if b["date"] == today) > mins[0]:
    p.load_page()
ch_n, ch_v = Counter(), Counter()
for b in p.bars():
    if b["date"] == today and b["t"] in mins:
        ch_n[b["t"]] += 1
        ch_v[b["t"]] += b["v"]

print(f"수신 {len(ev)}건, 비교 분 {len(mins)}개, 차트 페이지 {p.pages}\n")
print("  분     차트틱  실시간  누락   누락%   차트거래량  실시간거래량  거래소(실시간)")
tn = tr = tv = trv = 0
for m in mins:
    a, b = ch_n[m], rt_n[m]
    tn, tr, tv, trv = tn + a, tr + b, tv + ch_v[m], trv + rt_v[m]
    print(f"  {m:04d}  {a:6}  {b:6}  {a - b:5}  {(a - b) / a * 100 if a else 0:6.1f}%  "
          f"{ch_v[m]:10,}  {rt_v[m]:12,}   {dict(rt_x[m])}")
print(f"\n합계: 차트 {tn}틱 / 실시간 {tr}건 -> 누락 {tn - tr}건 ({(tn - tr) / tn * 100 if tn else 0:.1f}%), "
      f"거래량 차트 {tv:,} / 실시간 {trv:,}")
print(f"360틱봉 1개 기준 평균 누락 {(tn - tr) / tn * 360 if tn else 0:.1f}틱")
