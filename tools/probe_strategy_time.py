"""strategy 처리 시간 분해: 확정봉 1개 추가(지표 재계산) / Laya 첫 판단(모델 적재) / 이후 판단"""
import json
import socket
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from laya_trader import config, features as F  # noqa: E402
from laya_trader.laya_judge import Judge  # noqa: E402
from laya_trader.strategy import Book  # noqa: E402
from src.laya_gate import LayaGate  # noqa: E402

code = sys.argv[1] if len(sys.argv) > 1 else "005930"
period = int(sys.argv[2]) if len(sys.argv) > 2 else 360
s = socket.create_connection(("127.0.0.1", 8801), timeout=120)
rf = s.makefile("rb")


def call(method, **params):
    s.sendall((json.dumps({"id": "ptime", "method": method, "params": params}) + "\n").encode())
    while True:
        m = json.loads(rf.readline().decode("utf-8"))
        if m.get("id") == "ptime":
            if not m["ok"]:
                raise RuntimeError(m["error"])
            return m["result"]


bars = [b for b in call("bars", code=code, kind="T", period=period, min_ok=300)["bars"] if not b["live"]]
name = call("name", code=code)["name"]
day = bars[-1]["date"]
k0 = next(i for i, b in enumerate(bars) if b["date"] == day)
bk = Book(code, name, bars[:k0])
lat = []
for b in bars[k0:]:
    a = time.perf_counter()
    bk.add(b)
    lat.append((time.perf_counter() - a) * 1000)
print(f"[봉 추가] 전체 봉 {len(bars)}개 중 오늘 {len(lat)}개 추가: 합계 {sum(lat):.0f}ms, "
      f"1개당 평균 {sum(lat) / len(lat):.2f}ms 최대 {max(lat):.2f}ms")

a = time.perf_counter()
gate = LayaGate(config.load_yaml()["laya"])
judge = Judge(gate)
print(f"[Laya] 객체 생성 {(time.perf_counter() - a) * 1000:.0f}ms")
i = len(bk.bars) - 1
a = time.perf_counter()
snap = F.build(code, name, "T", period, bk.bars, bk.ind, i)
print(f"[피처] features.build {(time.perf_counter() - a) * 1000:.1f}ms, state {len(snap['state'])}자")
for n in range(1, 6):
    a = time.perf_counter()
    j = judge(snap["state"])
    print(f"[판단 {n}] {(time.perf_counter() - a) * 1000:.0f}ms (Judge 기록 {j['latency_ms']}ms) p_entry={j['p_entry']:.3f}")
