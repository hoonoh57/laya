"""strategy.py 단독 검증 (서버/엔진 변경 없음, 실행 중 브리지 8801에서 봉만 읽음)
[1] 추적 선정/해제 규칙(합성 시세)  [2] 오늘 확정봉을 1개씩 넣는 장중 재생 = 전체 계산  [3] 중복/끊김
python tools\test_strategy.py 005930 360"""
import asyncio
import json
import socket
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from laya_trader import config, ta, features as F  # noqa: E402
from laya_trader.strategy import Book, Strategy  # noqa: E402
from src.laya_gate import LayaGate  # noqa: E402


class Bridge:
    def __init__(self, port=8801):
        self.s = socket.create_connection(("127.0.0.1", port), timeout=120)
        self.r, self.n = self.s.makefile("rb"), 0

    def call(self, method, **params):
        self.n += 1
        rid = f"stest{self.n}"
        self.s.sendall((json.dumps({"id": rid, "method": method, "params": params}) + "\n").encode())
        while True:
            m = json.loads(self.r.readline().decode("utf-8"))
            if m.get("id") == rid:
                if not m["ok"]:
                    raise RuntimeError(m["error"])
                return m["result"]


class Hub:
    def __init__(self):
        self.ev = []

    async def emit(self, kind, data, store=True):
        self.ev.append((kind, data))


class Eng:
    def __init__(self, track, gate=None):
        self.cfg, self.gate, self.hub = {"track": track}, gate, Hub()
        self.account, self.cybos = {"holdings": []}, None


res = []


def check(name, ok, extra=""):
    res.append(bool(ok))
    print(f"  [{'OK' if ok else 'FAIL'}] {name} {extra}")


g = F._f
code = sys.argv[1] if len(sys.argv) > 1 else "005930"
period = int(sys.argv[2]) if len(sys.argv) > 2 else 360
db = ROOT / "data" / "test_strategy.db"
for sfx in ("", "-wal", "-shm"):
    Path(str(db) + sfx).unlink(missing_ok=True)

print("[1] 추적 선정/해제 (시가대비 2~20%, 1% 미만 30초 해제, 최대 3종목)")
e = Eng({"enabled": True, "min_open_pct": 2.0, "max_open_pct": 20.0, "release_gap": 1.0,
         "release_sec": 30, "max_n": 3})
s = Strategy(e, store_path=db)


def rows(**kw):
    return [{"code": k, "open": 100, "price": v} for k, v in kw.items()]


base = dict(A=103, B=101, C=125, D=105, E=110, F=102.5)
w = s.select(rows(**base), now=0, hm="10:00"); check("등락률 상위 3종목", w == ["E", "D", "A"], w); s.sent = w
w = s.select(rows(**dict(base, A=100.5)), now=100, hm="10:00"); check("하한 미만 직후 유지", "A" in w, w); s.sent = w
w = s.select(rows(**dict(base, A=100.5)), now=129, hm="10:00"); check("29초 경과 유지", "A" in w, w); s.sent = w
w = s.select(rows(**dict(base, A=100.5)), now=131, hm="10:00")
check("31초 해제 + 빈자리 F 편입", "A" not in w and "F" in w, w); s.sent = w
e.account["holdings"] = [{"code": "E"}]
w = s.select(rows(**dict(base, A=100.5, E=99)), now=200, hm="10:00"); s.sent = w
w = s.select(rows(**dict(base, A=100.5, E=99)), now=300, hm="10:00"); check("보유 종목은 하락해도 유지", "E" in w, w); s.sent = w
w = s.select(rows(**base), now=400, hm="15:30"); check("추적 시간대 밖 -> 보유만", w == ["E"], w); s.sent = w
e.cfg["track"]["enabled"] = False
w = s.select(rows(**base), now=500, hm="10:00"); check("전략 OFF -> 보유만", w == ["E"], w)

print("\n[2] 장중 재생: 오늘 확정봉을 1개씩 handle_close")
br = Bridge()
bars = [b for b in br.call("bars", code=code, kind="T", period=period, min_ok=300)["bars"] if not b["live"]]
name = br.call("name", code=code)["name"]
day = bars[-1]["date"]
k0 = next(i for i, b in enumerate(bars) if b["date"] == day)
full = ta.compute(bars)
ups = [i for i in range(max(k0, full["start"]), len(bars))
       if full["st"][i] and full["st"][i]["turn"] == 1 and bars[i]["session"] == "reg"]
cfg = config.load_yaml()
t0 = time.perf_counter()
gate = LayaGate(cfg["laya"])
print(f"  [{code} {name}] {period}틱 기준일 {day} 오늘 확정봉 {len(bars) - k0}개, 정규장 상승전환 {len(ups)}회 "
      f"| Laya 로딩 {time.perf_counter() - t0:.1f}s")
track = {"enabled": True, "min_open_pct": -30.0, "max_open_pct": 30.0, "entry_start": "09:00",
         "entry_end": "15:20", "kind": "T", "period": period}
e2 = Eng(track, gate)


async def replay():
    st = Strategy(e2, store_path=db)
    st.books[code] = Book(code, name, bars[:k0])
    a = time.perf_counter()
    for b in bars[k0:]:
        await st.handle_close(code, b)
    return st, time.perf_counter() - a


st2, sec = asyncio.run(replay())
bk = st2.books[code]
check("증분 지표 = 전체 계산 (ST/JMA 전 봉)", bk.ind["st"] == full["st"] and bk.ind["jma"] == full["jma"])
sigs = [d for k, d in e2.hub.ev if k == "signal"]
check("상승전환 판단 목록 = 전체 계산", [d["seq"] for d in sigs] == [bars[i]["seq"] for i in ups],
      f"{[d['seq'] for d in sigs]}")
rows_db = st2.store.rows(run_id=st2.run_id) if st2.store else []
idx = {(b["date"], b["seq"]): i for i, b in enumerate(bars)}
same_f = same_o = n_o = 0
for r in rows_db:
    i = idx[(r["date"], r["seq"])]
    same_f += F.build(code, name, "T", period, bars, full, i)["f"] == r["f"]
    if r["outcome"] is not None:
        n_o += 1
        same_o += F.outcome(bars, full, i) == r["outcome"]
check("저장 피처 = 전체 계산", rows_db and same_f == len(rows_db), f"{same_f}/{len(rows_db)}")
check("청산 결과 = 전체 계산", same_o == n_o, f"{same_o}/{n_o} (나머지 {len(rows_db) - n_o}건은 하락전환 대기)")
ent = [d for d in sigs if d["entry"]]
check("기준 진입 하루 1회 이하", len(ent) <= 1, f"{len(ent)}건")
print(f"\n  처리 {sec * 1000:.0f}ms (봉 {len(bars) - k0}개, 판단 {st2.stats['judged']}건) | stats {st2.stats}")
outs = {d["sid"]: d for k, d in e2.hub.ev if k == "signal_outcome"}
print("  시각  seq   p_entry 진입 사유                      -> 청산  사유      수익     MFE")
for d in sigs:
    o = outs.get(d["sid"])
    print("  {:>4} #{:<4} {:>6.3f}  {}  {:<24} -> {}".format(
        d["t"], d["seq"], d["p_entry"], "★" if d["entry"] else "-", ",".join(d["why"]) or "-",
        "{:>4} {:<8} {:>7} {:>6}".format(o["exit_t"], o["reason"], g(o["ret_pct"], "+.2f", "%"),
                                         g(o["mfe_pct"], "+.2f")) if o else "대기"))

print("\n[3] 중복/끊김 처리")
if len(bars) - k0 >= 7:
    b3 = Book(code, name, bars[:k0 + 5])
    check("같은 봉 다시 오면 무시", b3.add(bars[k0 + 4]) is None)
    check("seq 끊김 감지(-1)", b3.add(bars[k0 + 6]) == -1)
    check("정상 다음 봉 연결", b3.add(bars[k0 + 5]) == k0 + 5)
else:
    print("  오늘 확정봉 7개 미만 - 생략")
print("\n결과:", "통과" if all(res) else "실패 있음", f"({sum(res)}/{len(res)})")
