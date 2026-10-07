import sys
# 1) chart.html: URL 파라미터(code/kind/period) + 부모 창 종목연동(postMessage)
p = r"laya_trader\static\chart.html"
t = open(p, encoding="utf-8-sig").read().replace("\r\n", "\n")
a = 'fillPeriods();\nfetchBars("reset");'
n = '''const QP = new URLSearchParams(location.search);
if (QP.get("code")) $("code").value = QP.get("code");
if (QP.get("kind")) $("kind").value = QP.get("kind");
fillPeriods();
if (QP.get("period")) $("period").value = QP.get("period");
window.addEventListener("message", e => {
  if (e.origin !== location.origin) return;
  const m = e.data || {};
  if (m.type === "symbol" && m.code && m.code !== $("code").value.trim()) { $("code").value = m.code; fetchBars("reset"); }
});
fetchBars("reset");'''
if t.count(a) != 1:
    print("chart anchor not found - 중단"); sys.exit(1)
open(p, "w", encoding="utf-8").write(t.replace(a, n))
print("chart.html patched")

# 2) server.py: / -> desk.html, /classic -> 기존 화면, vendor css 타입
p = r"laya_trader\server.py"
raw = open(p, encoding="utf-8-sig", newline="").read()
crlf = "\r\n" in raw
t = raw.replace("\r\n", "\n")
a1 = '''@app.get("/")
async def index():
    return FileResponse(ROOT / "laya_trader" / "static" / "index.html")
'''
n1 = '''@app.get("/")
async def index():
    return FileResponse(ROOT / "laya_trader" / "static" / "desk.html")


@app.get("/classic")
async def classic():
    return FileResponse(ROOT / "laya_trader" / "static" / "index.html")
'''
a2 = 'return FileResponse(f, media_type="application/javascript")'
n2 = 'return FileResponse(f, media_type="text/css" if f.suffix == ".css" else "application/javascript")'
for a in (a1, a2):
    if t.count(a) != 1:
        print("server anchor not found - 중단:", a.strip()[:40]); sys.exit(1)
t = t.replace(a1, n1).replace(a2, n2)
if crlf:
    t = t.replace("\n", "\r\n")
open(p, "w", encoding="utf-8", newline="").write(t)
print("server.py patched")
