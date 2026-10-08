"""엔진 연결 검증 (서버 실행 중, 정규장): 추적 ON(시가대비 -30~30%, 최대 3종목) -> N초 관찰 -> 원래 설정 복구.
python tools\test_engine_track.py 120"""
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8755"
secs = int(sys.argv[1]) if len(sys.argv) > 1 else 120
CODES = ["005930", "000660", "035420"]
DEF = {"enabled": False, "min_open_pct": 2.0, "max_open_pct": 20.0, "max_n": 20,
       "track_start": "09:00", "track_end": "15:20"}


def get(p):
    with urllib.request.urlopen(BASE + p, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def post(p, body):
    req = urllib.request.Request(BASE + p, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


res = []


def chk(name, ok, extra=""):
    res.append(bool(ok))
    print(f"  [{'OK' if ok else 'FAIL'}] {name} {extra}")


t0 = time.time()
while True:
    try:
        st = get("/api/health")["status"]
        if st.get("laya") == "ready" and st.get("cybos_login"):
            break
    except Exception as e:  # noqa: BLE001
        st = {"error": repr(e)}
    if time.time() - t0 > 120:
        sys.exit(f"서버 준비 안 됨: {st}")
    time.sleep(3)
print(f"서버 준비: laya={st['laya']} cybos_login={st['cybos_login']} ({time.time() - t0:.0f}s 대기)")
s0 = get("/api/state")
warm = [e["data"].get("msg") for e in s0["events"].get("log", []) if "Laya 준비" in str(e["data"].get("msg"))]
print("워밍업 로그:", warm[0] if warm else "없음")
wl0 = list(s0["watchlist"])
tr0 = s0["settings"].get("track") or {}
print(f"관심종목 {len(wl0)}개 | 기존 track enabled={tr0.get('enabled')} 범위 {tr0.get('min_open_pct')}~{tr0.get('max_open_pct')}%")
r = None
try:
    post("/api/watchlist", {"codes": wl0 + [c for c in CODES if c not in wl0]})
    post("/api/settings", {"track": {"enabled": True, "min_open_pct": -30.0, "max_open_pct": 30.0, "max_n": 3,
                                     "track_start": "09:00", "track_end": "15:20"}})
    print(f"추적 ON (시가대비 -30~30%, 최대 3종목) {time.strftime('%H:%M:%S')}, {secs}초 관찰")
    end = time.time() + secs
    while time.time() < end:
        time.sleep(15)
        r = get("/api/track")["result"]
        sg, bg = r["strategy"], r["bridge"]
        items = " | ".join(f"{c} {v.get('name', '')} 봉{v.get('bars')} #{v.get('seq')} ST{'↑' if v.get('st_up') else '↓'}"
                           for c, v in sg["items"].items())
        print(f"  -- {time.strftime('%H:%M:%S')} {sg['stats']} 한도 {bg.get('limit_remain')} | {items}")
    sg, bg = r["strategy"], r["bridge"]
    print("\n[검증]")
    chk("추적 종목 1~3개", 1 <= len(sg["tracking"]) <= 3, sg["tracking"])
    chk("브리지 추적 = 전략 추적", set(bg.get("items", {})) == set(sg["tracking"]))
    for c in sg["tracking"]:
        s_seq = sg["items"][c].get("seq")
        b_last = (bg.get("items", {}).get(c) or {}).get("last") or [None, None]
        chk(f"{c} 확정봉 동기 (전략 #{s_seq} / 브리지 #{b_last[1]})",
            s_seq is not None and b_last[1] is not None and 0 <= b_last[1] - s_seq <= 1)
    chk("확정봉 처리됨", sg["stats"]["closes"] > 0, f"closes={sg['stats']['closes']}")
    chk("전략 오류 0", sg["stats"]["errors"] == 0 and not sg["last_err"], sg["last_err"] or "")
    sigs = [e["data"] for e in get("/api/state")["events"].get("signal", [])]
    print(f"  판단 이벤트(signal) {len(sigs)}건:",
          [(d["code"], d["t"], d["p_entry"], "★" if d["entry"] else ",".join(d["why"])) for d in sigs[:5]])
except Exception as e:  # noqa: BLE001
    chk("테스트 진행", False, repr(e))
finally:
    post("/api/settings", {"track": {**DEF, **tr0}})
    post("/api/watchlist", {"codes": wl0})
    time.sleep(8)
    r2 = get("/api/track")["result"]
    chk("복구: 추적 해제", not r2["strategy"]["tracking"] and not r2["bridge"].get("items"),
        f"strategy={r2['strategy']['tracking']} bridge={list(r2['bridge'].get('items', {}))}")
print("\n결과:", "통과" if all(res) else "실패 있음", f"({sum(res)}/{len(res)})")
