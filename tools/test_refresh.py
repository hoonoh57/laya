"""장중 확정 검증: refresh()로 이어 붙인 봉 == 새로 전체 수신한 봉 + 실시간 수신 + 조회 한도 측정.
python test_refresh.py A005930 360 180 2.5   (종목, 틱주기, 초, 재조회 간격)"""
import sys
import time
from pathlib import Path

import pythoncom
import win32com.client

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cybos_bridge"))
from chart_std import ChartPager  # noqa: E402

code = sys.argv[1] if len(sys.argv) > 1 else "A005930"
period = int(sys.argv[2]) if len(sys.argv) > 2 else 360
secs = int(sys.argv[3]) if len(sys.argv) > 3 else 180
gap = float(sys.argv[4]) if len(sys.argv) > 4 else 2.5
cp = win32com.client.Dispatch("CpUtil.CpCybos")
if not cp.IsConnect:
    sys.exit("Cybos 미연결 (관리자 권한 콘솔에서 실행)")
nxt = win32com.client.Dispatch("CpUtil.CpCodeMgr").IsNxtTrdPsbl(code)
rt_name = "Dscbo1.StockBsccnsCnld" if nxt else "Dscbo1.StockCur"
live = {"n": 0, "price": None}


class H:
    def init(self, obj):
        self.obj = obj

    def OnReceived(self):
        live["n"] += 1
        live["price"] = self.obj.GetHeaderValue(13)


def done(bs):
    return [b for b in bs if not b["live"]]


rem0 = cp.GetLimitRemainCount(1)
print(f"시세조회 남은 한도(시작) {rem0}, 한도 복구까지 {cp.LimitRequestRemainTime}ms | 실시간 {rt_name}")
a = time.perf_counter()
p = ChartPager(cp, code, "T", period)
p.ensure(300)
print(f"초기 수신 {p.pages}페이지 {(time.perf_counter() - a) * 1000:.0f}ms, 확정봉 {len(done(p.bars()))}개")
n_done = len(done(p.bars()))
o = win32com.client.Dispatch(rt_name)
h = win32com.client.WithEvents(o, H)
h.init(o)
o.SetInputValue(0, code)
o.Subscribe()

calls = fails = 0
lat, rem_min = [], rem0
nxt_t, end = time.time(), time.time() + secs
while time.time() < end:
    pythoncom.PumpWaitingMessages()
    time.sleep(0.005)
    if time.time() < nxt_t:
        continue
    nxt_t += gap
    a = time.perf_counter()
    r = p.refresh()
    lat.append((time.perf_counter() - a) * 1000)
    calls += 1
    if r < 0:
        fails += 1
        print("겹침 실패 -> 처음부터 다시 받기")
        p = ChartPager(cp, code, "T", period)
        p.ensure(300)
    rem_min = min(rem_min, cp.GetLimitRemainCount(1))
    bs = p.bars()
    d = done(bs)
    for b in d[n_done:]:
        print(f"{time.strftime('%H:%M:%S')} 확정 #{b['seq']:<4} t={b['t']} O={b['o']} H={b['h']} L={b['l']} "
              f"C={b['c']} V={b['v']} parts={b['parts']}")
    n_done = len(d)
    if calls % 12 == 0:
        lb = bs[-1]
        print(f"   잠정봉 #{lb['seq']} t={lb['t']} C={lb['c']} parts={lb['parts']} | 실시간 최근가 {live['price']} "
              f"(누적 {live['n']}건) | 남은 한도 {cp.GetLimitRemainCount(1)}")
o.Unsubscribe()

today = int(time.strftime("%Y%m%d"))
q = ChartPager(cp, code, "T", period)
q.ensure(300)
A = {(b["date"], b["seq"]): b for b in done(p.bars()) if b["date"] == today}
B = {(b["date"], b["seq"]): b for b in done(q.bars()) if b["date"] == today}
F = ("t", "o", "h", "l", "c", "v", "amt", "parts")
keys = sorted(set(A) & set(B))
bad = [k for k in keys if any(A[k][f] != B[k][f] for f in F)]
print(f"\n검증: 오늘 확정봉 이어받기 {len(A)} / 새로받기 {len(B)} / 공통 {len(keys)} / 일치 {len(keys) - len(bad)}")
for k in bad[:3]:
    print("  불일치", k, {f: (A[k][f], B[k][f]) for f in F if A[k][f] != B[k][f]})
print(f"refresh {calls}회, 실패 {fails}, 평균 {sum(lat) / len(lat):.0f}ms, 최대 {max(lat):.0f}ms | "
      f"남은 한도 최소 {rem_min} (시작 {rem0})")
print(f"실시간 수신 {live['n']}건")
