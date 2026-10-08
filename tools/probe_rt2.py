"""Cybos 실시간 체결 프로브 (객체 선택).
python probe_rt2.py <객체> <종목> <초>   예) StockBsccnsCnld A005930 60"""
import sys
import time
from collections import Counter

import pythoncom
import win32com.client

name = sys.argv[1] if len(sys.argv) > 1 else "StockBsccnsCnld"
code = sys.argv[2] if len(sys.argv) > 2 else "A005930"
secs = int(sys.argv[3]) if len(sys.argv) > 3 else 60
cp = win32com.client.Dispatch("CpUtil.CpCybos")
if not cp.IsConnect:
    sys.exit("Cybos 미연결 (관리자 권한 콘솔에서 실행)")
cm = win32com.client.Dispatch("CpUtil.CpCodeMgr")
print(f"NXT 거래가능: {cm.IsNxtTrdPsbl(code)}")
ev = []


class H:
    def init(self, obj):
        self.obj = obj

    def OnReceived(self):
        row = []
        for i in range(30):
            try:
                row.append(self.obj.GetHeaderValue(i))
            except Exception:
                row.append(None)
        ev.append((time.strftime("%H:%M:%S"), row))


def ch(x):
    if isinstance(x, int) and 32 <= x < 127:
        return chr(x)
    return str(x)


def num(x):
    try:
        return float(x)
    except Exception:
        return 0.0


o = win32com.client.Dispatch("Dscbo1." + name)
h = win32com.client.WithEvents(o, H)
h.init(o)
o.SetInputValue(0, code)
o.Subscribe()
print(f"Dscbo1.{name} {code} 구독, {secs}초 수신 (PC 시각 {time.strftime('%H:%M:%S')})")
end = time.time() + secs
while time.time() < end:
    pythoncom.PumpWaitingMessages()
    time.sleep(0.005)
o.Unsubscribe()

print(f"수신 {len(ev)}건")
if ev:
    print("헤더 0~29 (첫 건):")
    print("  " + " | ".join(f"{i}:{v}" for i, v in enumerate(ev[0][1])))
    print("\n받은시각  [18]초    [13]현재가 [17]수량 [9]누적거래량  [14]체결 [19] [20]장 [29]거래소")
    for t, r in (ev if len(ev) <= 12 else ev[:6] + ev[-6:]):
        print(f"{t}  {r[18]!s:>7} {r[13]!s:>10} {r[17]!s:>7} {r[9]!s:>13}   "
              f"{ch(r[14]):>4} {ch(r[19]):>4} {ch(r[20]):>4} {ch(r[29]):>6}")
    print("\n[20] 장구분:", dict(Counter(ch(r[20]) for _, r in ev)))
    print("[29] 거래소:", dict(Counter(ch(r[29]) for _, r in ev)))
if len(ev) >= 2:
    a, b = num(ev[0][1][9]), num(ev[-1][1][9])
    s = sum(num(r[17]) for _, r in ev[1:])
    print(f"누적거래량[9] 증가 {b - a:,.0f}  vs  수량[17] 합(첫 건 제외) {s:,.0f}  "
          f"-> {'일치' if abs((b - a) - s) < 1 else '불일치 (차이 %+.0f, 수신 누락 가능)' % ((b - a) - s)}")
    secs_seen = [num(r[18]) for _, r in ev]
    back = sum(1 for x, y in zip(secs_seen, secs_seen[1:]) if y < x)
    print(f"[18] 시각 역행 {back}건 (0이어야 순서 보장)")
