import sys
p = r"laya_trader\server.py"
raw = open(p, encoding="utf-8-sig", newline="").read()
crlf = "\r\n" in raw
t = raw.replace("\r\n", "\n")
a = '@app.post("/api/cybos/restart")\n'
n = '''@app.get("/api/bars")
async def bars(code: str, kind: str = "T", period: int = 120, more: bool = False,
               min_ok: int = 0, reset: bool = False):
    """Cybos 표준봉. kind=T(틱)/m(분), more=+이전페이지, min_ok=완전봉 최소 개수, reset=최신부터"""
    if kind not in ("T", "m") or period < 1:
        raise HTTPException(400, "kind는 T/m, period는 1 이상")
    return await act(engine.cybos.call("bars", timeout=120, code=code.strip(), kind=kind,
                                       period=period, more=more, min_ok=min_ok, reset=reset))


''' + a
if t.count(a) != 1 or "/api/bars" in t:
    print("anchor not found or already patched - 중단"); sys.exit(1)
t = t.replace(a, n)
if crlf:
    t = t.replace("\n", "\r\n")
open(p, "w", encoding="utf-8", newline="").write(t)
print("patched")
