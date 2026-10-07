import json, socket, time
for _ in range(30):
    try:
        s = socket.create_connection(("127.0.0.1", 8802), timeout=120); break
    except OSError:
        time.sleep(0.5)
f = s.makefile("rwb")
n = 0
def call(method, **params):
    global n
    n += 1
    f.write((json.dumps({"id": n, "method": method, "params": params}) + "\n").encode()); f.flush()
    while True:
        m = json.loads(f.readline())
        if m.get("id") == n:
            if not m["ok"]: raise RuntimeError(m["error"])
            return m["result"]
def show(tag, r):
    b = r["bars"]; ok = [x for x in b if x["day_ok"]]
    days = sorted({x["date"] for x in b})
    print(f"{tag}: {r['period']}{r['kind']} = base {r['base']} x {r['n']}  봉={len(b)} 완전봉={len(ok)} "
          f"페이지={r['pages']} 이전페이지={r['has_prev']} 날짜={days[0]}~{days[-1]}({len(days)}일)")
    print(f"   마지막: {b[-1]['date']} seq={b[-1]['seq']} t={b[-1]['t']} C={b[-1]['c']} live={b[-1]['live']}")
t0 = time.time(); show("360틱 min_ok=300", call("bars", code="005930", kind="T", period=360, min_ok=300)); print(f"   {time.time()-t0:.1f}s")
t0 = time.time(); show("360틱 +이전페이지", call("bars", code="005930", kind="T", period=360, more=True)); print(f"   {time.time()-t0:.1f}s")
t0 = time.time(); show("1분봉", call("bars", code="005930", kind="m", period=1)); print(f"   {time.time()-t0:.1f}s")
