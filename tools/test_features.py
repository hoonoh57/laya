"""features.py 단독 검증: 미래참조 없음(재현성) + 상승전환별 기준 결과 + 현재 Laya state"""
import json, socket, sys, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from laya_trader import ta, features as F  # noqa: E402


class Bridge:
    def __init__(self, port=8801):
        self.s = socket.create_connection(("127.0.0.1", port), timeout=120)
        self.r, self.n = self.s.makefile("rb"), 0

    def call(self, method, **params):
        self.n += 1
        rid = f"ftest{self.n}"
        self.s.sendall((json.dumps({"id": rid, "method": method, "params": params}) + "\n").encode())
        while True:
            m = json.loads(self.r.readline().decode("utf-8"))
            if m.get("id") == rid:
                if not m["ok"]:
                    raise RuntimeError(m["error"])
                return m["result"]


g = F._f
code = sys.argv[1] if len(sys.argv) > 1 else "005930"
kind, period = "T", int(sys.argv[2]) if len(sys.argv) > 2 else 360
br = Bridge()
bars = br.call("bars", code=code, kind=kind, period=period, min_ok=300)["bars"]
t0 = time.perf_counter()
ind = ta.compute(bars)
name = br.call("name", code=code)["name"]
ob = br.call("orderbook_snapshot", code=code)
try:
    wl = json.load(urllib.request.urlopen("http://127.0.0.1:8755/api/state", timeout=5))["watchlist"]
except Exception:
    wl = []
codes = list(dict.fromkeys([code] + wl))
for c in ("000660", "035420", "005380", "051910", "068270", "035720", "105560"):
    if len(codes) >= 8:
        break
    if c not in codes:
        codes.append(c)
peers = br.call("marketeye", codes=codes[:200])["rows"]

last = max(i for i, b in enumerate(bars) if not b["live"])
day = bars[last]["date"]
ups = [i for i in range(ind["start"], last + 1) if bars[i]["date"] == day and ind["st"][i]
       and ind["st"][i]["turn"] == 1 and bars[i]["session"] == "reg"]
print(f"[{code} {name}] {period}틱 봉 {len(bars)}  계산시작 {ind['start']}  기준일 {day}  정규장 상승전환 {len(ups)}회")

bad = 0
for i in ups + [last]:
    a = F.build(code, name, kind, period, bars, ind, i)
    b = F.build(code, name, kind, period, bars[:i + 1], ta.compute(bars[:i + 1]), i)
    if a["f"] != b["f"] or a["state"] != b["state"] or a["window"] != b["window"]:
        bad += 1
        print("  미래참조 의심 idx", i)
print(f"재현성(그 봉까지 잘라 재계산 = 전체 계산): {len(ups) + 1 - bad}/{len(ups) + 1} 일치")

print("\n  시각  seq   시가대비  ST거리  JMA     r3      거래량  5봉  -> 청산  사유     봉수  수익     MFE     MAE")
tot = 0.0
for n, i in enumerate(ups):
    f, o = F.build(code, name, kind, period, bars, ind, i)["f"], F.outcome(bars, ind, i)
    tot += o["ret_pct"] or 0
    print("{} {:>4} #{:<4} {:>8} {:>6} {:>2}/{:<5} {:>7} x{:>4} {:>3}분 -> {:>4} {:<8} {:>3} {:>7} {:>7} {:>7}".format(
        "★" if n == 0 else " ", f["t"], f["seq"], g(f["chg_open_pct"], "+.2f", "%"), g(f["dist_st_atr"], "+.2f"),
        f["jma_dir"], g(f["jma_bp3"], "+.1f"), g(f["r3"], "+.2f", "%"), g(f["vol_ratio"], ".1f"),
        g(f["span5_min"], "d"), o["exit_t"], o["reason"], o["bars"],
        g(o["ret_pct"], "+.2f", "%"), g(o["mfe_pct"], "+.2f"), g(o["mae_pct"], "+.2f")))
print(f"  (★ = 하루 1회 규칙의 첫 진입, 전체 {len(ups)}회 단순합 {tot:+.2f}%)")

snap = F.build(code, name, kind, period, bars, ind, last, ob, peers)
print(f"\n[마지막 완성봉 #{bars[last]['seq']} {bars[last]['t']} Laya state]")
print(json.dumps(snap["state"], ensure_ascii=False, indent=1))
print("state {}자 / 피처 {}개 / window {}봉 / 처리 {:.1f}ms".format(
    len(json.dumps(snap["state"], ensure_ascii=False)), len(snap["f"]), len(snap["window"]),
    (time.perf_counter() - t0) * 1000))
print("호가/비교:", {k: snap["f"].get(k) for k in ("ob_time", "spread_pct", "imb5", "imb_total",
                                                  "peer_n", "rate", "rate_pctile", "value_pctile")})
