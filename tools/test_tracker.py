"""정밀 추적 단독 검증 (브리지/서버 무관, 같은 Tracker 코드 사용).
python test_tracker.py 005930,000660,035420 360 180   (종목들, 틱주기, 초)"""
import sys
import time
from pathlib import Path

import pythoncom
import win32com.client

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cybos_bridge"))
from chart_std import ChartPager  # noqa: E402
from tracker import Tracker, acode  # noqa: E402

codes = sys.argv[1].split(",") if len(sys.argv) > 1 else ["005930", "000660", "035420"]
period = int(sys.argv[2]) if len(sys.argv) > 2 else 360
secs = int(sys.argv[3]) if len(sys.argv) > 3 else 180
cp = win32com.client.Dispatch("CpUtil.CpCybos")
if not cp.IsConnect:
    sys.exit("Cybos 미연결 (관리자 권한 콘솔에서 실행)")
cm = win32com.client.Dispatch("CpUtil.CpCodeMgr")
sent, nlive = {}, {}


def emit(msg):
    ev, d = msg["event"], msg["data"]
    if ev == "bar_close":
        b = d["bar"]
        sent.setdefault(d["code"], []).append(b)
        print(f"{time.strftime('%H:%M:%S')} 확정 {d['code']} #{b['seq']:<4} t={b['t']} "
              f"C={b['c']} V={b['v']} parts={b['parts']}")
    elif ev == "bar_live":
        nlive[d["code"]] = nlive.get(d["code"], 0) + 1
    else:
        print(time.strftime("%H:%M:%S"), ev, d)


def log(*a):
    print(time.strftime("%H:%M:%S"), *a)


rem0 = cp.GetLimitRemainCount(1)
tr = Tracker(cp, cm, emit, log)
a = time.perf_counter()
r = tr.set(codes, "T", period, 300)
print(f"추적 시작 {r['tracking']} 오류 {r['errors']} | 초기 수신 {(time.perf_counter() - a) * 1000:.0f}ms | 시작 한도 {rem0}")
for c, it in tr.items.items():
    print(f"  {c} {cm.CodeToName(acode(c))} 실시간={it.rt.split('.')[-1]} 마지막 확정봉={it.last_key}")
rem_min, t0 = rem0, time.time()
end, rep = t0 + secs, t0 + 30
while time.time() < end:
    pythoncom.PumpWaitingMessages()
    tr.tick()
    rem_min = min(rem_min, cp.GetLimitRemainCount(1))
    time.sleep(0.005)
    if time.time() >= rep:
        rep += 30
        s = tr.status()
        print(f"  -- {time.strftime('%H:%M:%S')} 남은 한도 {s['limit_remain']} 미룸 {s['deferred']} | " + " | ".join(
            f"{c} 조회{v['calls']} 확정{v['confirmed']} 간격{v['avg_iv']}s 체결{v['ticks']}"
            for c, v in s["items"].items()))

st = tr.status()
d = int(time.strftime("%Y%m%d"))
mine = {c: [b for b in it.pager.bars() if not b["live"] and b["date"] == d] for c, it in tr.items.items()}
tr.clear()
mins = (time.time() - t0) / 60
F = ("t", "o", "h", "l", "c", "v", "amt", "parts")
print(f"\n[검증] {mins:.1f}분")
all_ok, total = True, 0
for c in mine:
    q = ChartPager(cp, acode(c), "T", period)
    q.ensure(300)
    A = {(b["date"], b["seq"]): b for b in mine[c]}
    B = {(b["date"], b["seq"]): b for b in q.bars() if not b["live"] and b["date"] == d}
    keys = sorted(set(A) & set(B))
    bad = [k for k in keys if any(A[k][f] != B[k][f] for f in F)]
    missing = sorted(set(A) - set(B))
    ev = sent.get(c, [])
    ev_bad = [b for b in ev if (b["date"], b["seq"]) not in B
              or any(b[f] != B[(b["date"], b["seq"])][f] for f in F)]
    v = st["items"][c]
    total += v["calls"]
    ok = not bad and not missing and not ev_bad and v["resets"] == 0
    all_ok &= ok
    print(f"  {c}: 확정봉 이어받기 {len(A)} / 새로받기 {len(B)} / 일치 {len(keys) - len(bad)}/{len(keys)}"
          f" | 이벤트 확정 {len(ev)}건(불일치 {len(ev_bad)}) {'OK' if ok else '불일치'}")
    print(f"      조회 {v['calls']}회(분당 {v['calls'] / mins:.1f}) 실패 {v['fails']} 재수신 {v['resets']}"
          f" 평균 {v['lat_avg']}ms 최대 {v['lat_max']}ms | 봉간격 {v['avg_iv']}s 봉당 수신체결 {v['tpb']}")
    print(f"      실시간 체결 {v['ticks']}건 잠정봉 전송 {nlive.get(c, 0)}회 | 누적거래량 정합(중앙값) {v['vol_gap_med']}주")
    for k in bad[:2]:
        print("      불일치", k, {f: (A[k][f], B[k][f]) for f in F if A[k][f] != B[k][f]})
print(f"\n전체 조회 {total}회 (분당 {total / mins:.1f}) | 남은 한도 최소 {rem_min} (시작 {rem0}) | 한도 부족으로 미룸 {st['deferred']}회")
print("결과:", "통과" if all_ok else "불일치 있음")
