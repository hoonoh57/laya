"""laya_judge 단독 검증: 상승전환별 Laya 판단 -> 스냅샷 저장 -> DB에서 읽어 재현"""
import json, socket, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from laya_trader import ta, config, features as F  # noqa: E402
from laya_trader.laya_judge import Judge, SnapStore  # noqa: E402
from src.laya_gate import LayaGate  # noqa: E402


class Bridge:
    def __init__(self, port=8801):
        self.s = socket.create_connection(("127.0.0.1", port), timeout=120)
        self.r, self.n = self.s.makefile("rb"), 0

    def call(self, method, **params):
        self.n += 1
        rid = f"jtest{self.n}"
        self.s.sendall((json.dumps({"id": rid, "method": method, "params": params}) + "\n").encode())
        while True:
            m = json.loads(self.r.readline().decode("utf-8"))
            if m.get("id") == rid:
                if not m["ok"]:
                    raise RuntimeError(m["error"])
                return m["result"]


g = F._f
code = sys.argv[1] if len(sys.argv) > 1 else "005930"
period = int(sys.argv[2]) if len(sys.argv) > 2 else 360
br = Bridge()
bars = br.call("bars", code=code, kind="T", period=period, min_ok=300)["bars"]
ind = ta.compute(bars)
name = br.call("name", code=code)["name"]
last = max(i for i, b in enumerate(bars) if not b["live"])
day = bars[last]["date"]
ups = [i for i in range(ind["start"], last + 1) if bars[i]["date"] == day and ind["st"][i]
       and ind["st"][i]["turn"] == 1 and bars[i]["session"] == "reg"]

cfg = config.load_yaml()
t0 = time.perf_counter()
gate = LayaGate(cfg["laya"])
judge = Judge(gate)
p_min = float((cfg.get("gate") or {}).get("min_p_entry", 0.6))
print(f"[{code} {name}] {period}틱 기준일 {day} 상승전환 {len(ups)}회 | 모델 {judge.ckpt} "
      f"device={cfg['laya'].get('device')} 로딩 {time.perf_counter() - t0:.1f}s | 승인기준 p>={p_min}")

store = SnapStore(ROOT / "data" / "snapshots.db")
run_id = "replay-" + time.strftime("%Y%m%d-%H%M%S")
judge(F.build(code, name, "T", period, bars, ind, ups[0])["state"])   # GPU 워밍업(저장 안 함)

print("\n  시각  seq   p_entry 판정 quality basis     regime     지연    -> 청산  수익     MFE")
for n, i in enumerate(ups):
    snap = F.build(code, name, "T", period, bars, ind, i)
    j = judge(snap["state"])
    o = F.outcome(bars, ind, i)
    ok = j["p_entry"] >= p_min
    store.save("replay", run_id, snap, j, ok, o)
    print("{} {:>4} #{:<4} {:>6.3f}  {}  {:>6} {:<9} {:<9} {:>6.1f}ms -> {:>4} {:>7} {:>6}".format(
        "★" if n == 0 else " ", snap["f"]["t"], snap["f"]["seq"], j["p_entry"], "승인" if ok else "거절",
        g(j["quality"], ".2f"), str(j["basis"]), str(j["regime"]), j["latency_ms"],
        o["exit_t"], g(o["ret_pct"], "+.2f", "%"), g(o["mfe_pct"], "+.2f")))

rows = store.rows(run_id=run_id)
same_p = same_f = 0
max_d = 0.0
for r in rows:
    j2 = judge(r["state"])
    d = abs(j2["p_entry"] - r["p_entry"])
    max_d = max(max_d, d)
    same_p += d < 1e-3 and j2["basis"] == r["basis"]
    i = next(k for k, b in enumerate(bars) if b["date"] == r["date"] and b["seq"] == r["seq"])
    same_f += F.build(code, name, "T", period, bars, ind, i)["f"] == r["f"]
print(f"\n저장 {len(rows)}건 (DB 전체 {store.count()}건) run_id={run_id}")
print(f"재현: 저장 state로 재판단 일치 {same_p}/{len(rows)} (최대 p 차이 {max_d:.5f}), "
      f"저장 피처 = 봉 재계산 {same_f}/{len(rows)}")
r0 = rows[0]
print("근거 확률(첫 건):", r0["judge"]["basis_p"])
print("장세 확률(첫 건):", r0["judge"]["regime_p"])
print("entry 원본 응답:", json.dumps(r0["judge"]["answers"]["entry"], ensure_ascii=False)[:300])
