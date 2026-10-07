import sys
p = r"laya_trader\server.py"
raw = open(p, encoding="utf-8-sig", newline="").read()
crlf = "\r\n" in raw
t = raw.replace("\r\n", "\n")
a = '@app.get("/api/health")\n'
n = '''@app.get("/chart")
async def chart_page():
    return FileResponse(ROOT / "laya_trader" / "static" / "chart.html")


@app.get("/vendor/{name}")
async def vendor(name: str):
    f = ROOT / "laya_trader" / "static" / "vendor" / os.path.basename(name)
    if not f.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(f, media_type="application/javascript")


''' + a
if t.count(a) != 1 or '"/chart"' in t:
    print("anchor not found or already patched - 중단"); sys.exit(1)
t = t.replace(a, n)
if crlf:
    t = t.replace("\n", "\r\n")
open(p, "w", encoding="utf-8", newline="").write(t)
print("patched")
