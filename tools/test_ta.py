import json, sys, time, urllib.request
sys.path.insert(0, "laya_trader")
import ta
assert ta.round_even(1.00005, 4) == 1.0 and ta.round_even(1.00015, 4) == 1.0002, "ToEven 실패"
u = "http://127.0.0.1:8755/api/bars?code=005930&kind=T&period=360&min_ok=300&reset=true"
bars = json.load(urllib.request.urlopen(u, timeout=120))["result"]["bars"]
t0 = time.perf_counter(); r = ta.compute(bars); ms = (time.perf_counter() - t0) * 1000
print(f"봉 {len(bars)}  계산시작 index {r['start']}  계산 {ms:.1f}ms")
turns = {}
for b, s in zip(bars, r["st"]):
    if s and s["turn"]:
        turns.setdefault(b["date"], []).append(("상승" if s["turn"] > 0 else "하락", b["t"], b["seq"]))
for d, v in turns.items():
    print(f" {d} ST전환 {len(v)}회  처음3개 {v[:3]}")
print(" 마지막 3봉:")
for b, s, j in list(zip(bars, r["st"], r["jma"]))[-3:]:
    print(f"  {b['date']} {b['t']:>4} #{b['seq']:<4} C={b['c']:<7} ST={s['v']:<10} {'상승' if s['up'] else '하락'}  JMA={j['v']:<10} dir={j['dir']:+d} slope={j['slope']}")
