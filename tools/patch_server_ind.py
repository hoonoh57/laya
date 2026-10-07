import sys
p = r"laya_trader\server.py"
raw = open(p, encoding="utf-8-sig", newline="").read()
crlf = "\r\n" in raw
t = raw.replace("\r\n", "\n")
if "ta.compute" in t:
    print("already patched - 중단"); sys.exit(1)
imp = "from . import config\n"
if t.count(imp) != 1:
    print("anchor(import) not found - 중단"); sys.exit(1)
t = t.replace(imp, "from . import config, ta\n")
s = t.find('@app.get("/api/bars")\n')
e = t.find("\n\n\n", s)
if s < 0 or e < 0:
    print("anchor(/api/bars) not found - 중단"); sys.exit(1)
NEW = '''@app.get("/api/bars")
async def bars(code: str, kind: str = "T", period: int = 120, more: bool = False,
               min_ok: int = 0, reset: bool = False,
               st_period: int = 14, st_mult: float = 2.0,
               jma_period: int = 14, jma_phase: int = 50, jma_power: int = 2):
    """Cybos 표준봉 + 서버 계산 지표(ta.py, kiwoom-desk 포팅). 지표는 서버 계산이 원본."""
    if kind not in ("T", "m") or period < 1:
        raise HTTPException(400, "kind는 T/m, period는 1 이상")

    async def _get():
        r = await engine.cybos.call("bars", timeout=120, code=code.strip(), kind=kind,
                                    period=period, more=more, min_ok=min_ok, reset=reset)
        r["ind"] = ta.compute(r["bars"], st_period, st_mult, jma_period, jma_phase, jma_power)
        return r
    return await act(_get())'''
CHART = """@app.get("/chart")
async def chart_page():
    return FileResponse(ROOT / "laya_trader" / "static" / "chart.html")


@app.get("/vendor/{name}")
async def vendor(name: str):
    f = ROOT / "laya_trader" / "static" / "vendor" / os.path.basename(name)
    if not f.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(f, media_type="application/javascript")


"""
t = t[:s] + NEW + t[e:]
if '"/chart"' not in t:
    a = '@app.get("/api/health")\n'
    if t.count(a) != 1:
        print("anchor(/api/health) not found - 중단"); sys.exit(1)
    t = t.replace(a, CHART + a)
    print("chart route added")
if crlf:
    t = t.replace("\n", "\r\n")
open(p, "w", encoding="utf-8", newline="").write(t)
print("patched")
