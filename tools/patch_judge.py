import py_compile
from pathlib import Path

R = Path(r"E:\2026\laya")
p = R / "laya_trader" / "features.py"
t = p.read_text(encoding="utf-8-sig")
old = '    me = next((r for r in rows if r["code"] == code), None)'
new = ('    if rows and not any((r.get("value") or 0) for r in rows):\n'
       '        return {"peer_n": len(rows), "peer_stale": True}   # 장후 시세 초기화(거래대금 전부 0)\n'
       + old)
if '"peer_stale"' in t:
    print("features: 이미 적용 - 건너뜀")
elif t.count(old) == 1:
    p.with_suffix(".py.bak3").write_text(t, encoding="utf-8")
    p.write_text(t.replace(old, new), encoding="utf-8")
    print("features: peer_stale patched (백업 features.py.bak3)")
else:
    raise SystemExit(f"features anchor {t.count(old)}개 - 중단 (파일 변경 없음)")

gi = R / ".gitignore"
gt = gi.read_text(encoding="utf-8")
if "data/*.db*" in gt:
    print(".gitignore: 이미 있음")
else:
    gi.write_text(gt.rstrip("\n") + "\ndata/*.db*\n", encoding="utf-8")
    print(".gitignore: data/*.db* 추가")

for f in ("laya_trader/features.py", "laya_trader/laya_judge.py", "tools/test_judge.py"):
    py_compile.compile(str(R / f), doraise=True)
print("compile OK")
