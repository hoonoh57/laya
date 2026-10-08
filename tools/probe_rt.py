"""Cybos 실시간 체결(Dscbo1.StockCur) 프로브: 필드 위치 / NXT 프리마켓 수신 여부 / 누적거래량 정합.
실행: 32bit 파이썬 + 관리자 권한 콘솔.  python probe_rt.py [A005930] [초]"""
import sys
import time

import pythoncom
import win32com.client

code = sys.argv[1] if len(sys.argv) > 1 else "A005930"
secs = int(sys.argv[2]) if len(sys.argv) > 2 else 60
cp = win32com.client.Dispatch("CpUtil.CpCybos")
if not cp.IsConnect:
    sys.exit("Cybos 미연결 (관리자 권한 콘솔에서 실행)")
ev = []


class H:
    def init(self, obj):
        self.obj = obj

    def OnReceived(self):
        row = []
        for i in range(32):
            try:
                row.append(self.obj.GetHeaderValue(i))
            except Exception:
                row.append("ERR")
        ev.append((time.strftime("%H:%M:%S"), row))


def num(x):
    try:
        return float(x)
    except Exception:
        return None


def ch(x):
    return chr(x) if isinstance(x, int) and 32 <= x < 127 else repr(x)


o = win32com.client.Dispatch("Dscbo1.StockCur")
h = win32com.client.WithEvents(o, H)
h.init(o)
o.SetInputValue(0, code)
o.Subscribe()
print(f"{code} StockCur 구독, {secs}초 수신 (PC 시각 {time.strftime('%H:%M:%S')})")
end = time.time() + secs
while time.time() < end:
    pythoncom.PumpWaitingMessages()
    time.sleep(0.005)
o.Unsubscribe()

print(f"수신 {len(ev)}건")
for t, row in ev[:3]:
    print(f"--- 받은시각 {t} 헤더 0~31")
    print("  " + " | ".join(f"{i}:{v}" for i, v in enumerate(row)))
if ev:
    print("\n받은시각  [3]     [18]     [13]현재가  [17]수량  [9]누적거래량  [19] [20] [21]")
    sample = ev if len(ev) <= 10 else ev[:5] + ev[-5:]
    for t, r in sample:
        print(f"{t}  {r[3]!s:>6} {r[18]!s:>8} {r[13]!s:>11} {r[17]!s:>8} {r[9]!s:>13}   "
              f"{ch(r[19]):>3}  {ch(r[20]):>3}  {ch(r[21]):>3}")
if len(ev) >= 2:
    a, b = num(ev[0][1][9]), num(ev[-1][1][9])
    s = sum(num(r[17]) or 0 for _, r in ev[1:])
    print(f"\n누적거래량[9] 증가 {b - a:,.0f}  vs  수량[17] 합(첫 건 제외) {s:,.0f}  -> {'일치' if abs((b - a) - s) < 1 else '불일치'}")
    for k in (19, 20, 21):
        print(f"[{k}] 값 종류: {sorted({ch(r[k]) for _, r in ev})}")
