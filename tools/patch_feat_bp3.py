import py_compile, re, sys
from pathlib import Path

p = Path(r"E:\2026\laya\laya_trader\features.py")
t = p.read_text(encoding="utf-8-sig")
nl = "\r\n" if "\r\n" in t else "\n"
old = '"jma_gap_pct": _pct(c, jm["v"]),'
add = '        "jma_bp3": (jm["v"] / ind["jma"][idx - 3]["v"] - 1) * 10000 if idx - 3 >= start and ind["jma"][idx - 3] else None,'

if '"jma_bp3": (' in t:
    print("이미 추가됨 - 건너뜀")
elif t.count(old) != 1:
    print(f"anchor {t.count(old)}개 - 중단 (파일 변경 없음)")
    sys.exit(1)
else:
    p.with_suffix(".py.bak2").write_text(t, encoding="utf-8")
    p.write_text(t.replace(old, old + nl + add), encoding="utf-8")
    print("feature patched (백업 features.py.bak2)")

py_compile.compile(str(p), doraise=True)
print("compile OK")
for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
    if re.search(r"jma_bp3|3-bar", line):
        print(f"{i:4}: {line.strip()[:110]}")
