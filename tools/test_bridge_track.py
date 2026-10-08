"""브리지 정밀 추적 단독 검증 (64bit에서 실행).
패치된 cybos_bridge.py를 별도 포트 8802로 띄워 socket 프로토콜로만 확인. 실행 중 서버/8801 브리지와 무관.
python test_bridge_track.py "005930,000660,035420" 360 120   (종목들, 틱주기, 초)"""
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY32 = r"E:\Python310-32\python.exe"
PORT = 8802
codes = [c.strip() for c in (sys.argv[1] if len(sys.argv) > 1 else "005930,000660,035420").split(",") if c.strip()]
period = int(sys.argv[2]) if len(sys.argv) > 2 else 360
secs = int(sys.argv[3]) if len(sys.argv) > 3 else 120
F = ("t", "o", "h", "l", "c", "v", "amt", "parts")

(ROOT / "logs").mkdir(exist_ok=True)
log_path = ROOT / "logs" / "test_bridge_track.log"
logf = open(log_path, "wb")
proc = subprocess.Popen([PY32, str(ROOT / "cybos_bridge" / "cybos_bridge.py"), str(PORT), str(os.getpid())],
                        stdout=logf, stderr=subprocess.STDOUT, cwd=str(ROOT),
                        env=dict(os.environ, PYTHONIOENCODING="utf-8"))


def tail():
    logf.flush()
    return log_path.read_bytes().decode("utf-8", "replace")[-1500:]


sock, t0 = None, time.time()
while time.time() - t0 < 20 and proc.poll() is None:
    try:
        sock = socket.create_connection(("127.0.0.1", PORT), timeout=1)
        break
    except OSError:
        time.sleep(0.3)
if sock is None:
    print("브리지 연결 실패 (exit", proc.poll(), ")\n" + tail())
    proc.kill()
    sys.exit(1)
sock.settimeout(None)
pending, events, lock = {}, [], threading.Lock()


def reader():
    buf = b""
    while True:
        try:
            chunk = sock.recv(65536)
        except OSError:
            return
        if not chunk:
            return
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            if not line.strip():
                continue
            m = json.loads(line.decode("utf-8"))
            if "event" in m:
                with lock:
                    events.append((m["event"], m["data"]))
            elif m.get("id") in pending:
                pending[m["id"]][1] = m
                pending[m["id"]][0].set()


threading.Thread(target=reader, daemon=True).start()
rid = [0]


def call(method, timeout=90, **params):
    rid[0] += 1
    i = rid[0]
    ent = pending[i] = [threading.Event(), None]
    a = time.perf_counter()
    sock.sendall((json.dumps({"id": i, "method": method, "params": params}) + "\n").encode("utf-8"))
    if not ent[0].wait(timeout):
        raise TimeoutError(method)
    pending.pop(i, None)
    m = ent[1]
    if not m["ok"]:
        raise RuntimeError(f"{method}: {m['error']}")
    return m["result"], (time.perf_counter() - a) * 1000


ok = False
try:
    st, ms = call("status")
    print(f"브리지 8802 시작 connected={st['connected']} admin={st['admin']} "
          f"tracking필드={'tracking' in st} ({ms:.0f}ms)")
    if not st["connected"]:
        raise RuntimeError("Cybos 미연결")
    r, ms = call("track_set", codes=codes, kind="T", period=period, min_ok=300)
    print(f"track_set {ms:.0f}ms -> 추적 {r['tracking']} 오류 {r['errors']}")
    rtt = []
    end, rep = time.time() + secs, time.time() + 20
    while time.time() < end:
        time.sleep(0.2)
        if time.time() >= rep:
            rep += 20
            s, ms = call("track_status")
            rtt.append(ms)
            with lock:
                nl = sum(1 for e in events if e[0] == "bar_live")
                nc = sum(1 for e in events if e[0] == "bar_close")
            print(f"  -- {time.strftime('%H:%M:%S')} track_status 응답 {ms:.0f}ms | 남은 한도 {s['limit_remain']} "
                  f"미룸 {s['deferred']} | 잠정봉 이벤트 {nl} 확정 이벤트 {nc}")
    s, _ = call("track_status")
    with lock:
        ev = list(events)
    d = int(time.strftime("%Y%m%d"))
    mins = secs / 60
    print(f"\n[검증] {mins:.1f}분, 수신 이벤트 {len(ev)}건")
    ok = bool(r["tracking"]) and not r["errors"]
    for c in r["tracking"]:
        ref, _ = call("bars", code=c, kind="T", period=period, min_ok=300, reset=True)
        B = {(b["date"], b["seq"]): b for b in ref["bars"] if not b["live"] and b["date"] == d}
        closes = [e[1]["bar"] for e in ev if e[0] == "bar_close" and e[1]["code"] == c]
        lives = [e[1]["bar"] for e in ev if e[0] == "bar_live" and e[1]["code"] == c]
        bad = [b for b in closes if (b["date"], b["seq"]) not in B
               or any(b[f] != B[(b["date"], b["seq"])][f] for f in F)]
        seqs = [b["seq"] for b in closes]
        gap = any(y != x + 1 for x, y in zip(seqs, seqs[1:]))
        lbad = sum(1 for b in lives if not (b["l"] <= b["c"] <= b["h"]))
        v = s["items"][c]
        good = not bad and not gap and lbad == 0 and v["resets"] == 0
        ok &= good
        print(f"  {c} {v['name']}: 확정 이벤트 {len(closes)}건 seq {seqs[0] if seqs else '-'}~{seqs[-1] if seqs else '-'}"
              f" 원본일치 {len(closes) - len(bad)}/{len(closes)} 연속 {'OK' if not gap else '끊김'}"
              f" | {'OK' if good else '불일치'}{'' if closes else ' (확정 없음 - 거래 뜸함)'}")
        print(f"      잠정봉 이벤트 {len(lives)}건(가격범위 오류 {lbad}) | 조회 {v['calls']}회(분당 {v['calls'] / mins:.1f})"
              f" 평균 {v['lat_avg']}ms | 거래량 정합 {v['vol_gap_med']}주")
        for b in bad[:2]:
            k = (b["date"], b["seq"])
            print("      불일치", k, {f: (b[f], B[k][f]) for f in F if k in B and b[f] != B[k][f]} if k in B else "원본에 없음")
    if rtt:
        print(f"\n브리지 응답(track_status) 평균 {sum(rtt) / len(rtt):.0f}ms 최대 {max(rtt):.0f}ms")
    r2, _ = call("track_set", codes=[])
    st2, _ = call("status")
    print(f"해제: removed={r2['removed']} 남은 추적={st2['tracking']}")
    ok &= not st2["tracking"]
except Exception as e:  # noqa: BLE001
    print("테스트 오류:", repr(e))
finally:
    try:
        sock.close()
    except OSError:
        pass
    proc.terminate()
    try:
        proc.wait(5)
    except subprocess.TimeoutExpired:
        proc.kill()
    errs = [x for x in tail().splitlines() if "error" in x.lower() or "Traceback" in x]
    print("브리지 로그 오류:", errs[-5:] if errs else "없음")
print("결과:", "통과" if ok else "불일치/오류 있음")
