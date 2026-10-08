import py_compile
from pathlib import Path

p = Path(r"E:\2026\laya\cybos_bridge\chart_std.py")
t = p.read_text(encoding="utf-8-sig")
nl = "\r\n" if "\r\n" in t else "\n"
REFRESH = '''    def refresh(self, tail=60):
        """최근 base봉 tail개만 다시 받아 끝부분 교체(장중 확정용).
        완성된 base봉은 바뀌지 않으므로 '직전 완성봉 5개'가 겹치는 위치를 찾아 이어 붙인다.
        반환: 새로 완성된 base봉 수(0 이상), -1 = 겹침 실패(호출측에서 처음부터 다시 받기)"""
        m = 5
        if len(self.raw) < m + 1:
            return -1
        key = self.raw[-(m + 1):-1]
        for size in (tail, self.page):
            ch = self._make(size)
            while self.cp.GetLimitRemainCount(1) <= 0:
                time.sleep(0.05)
            ch.BlockRequest()
            if ch.GetDibStatus() != 0:
                raise RuntimeError(ch.GetDibMsg1())
            cnt = ch.GetHeaderValue(3)
            rows = [tuple(ch.GetDataValue(f, i) for f in range(len(FIELDS))) for i in range(cnt)]
            rows.reverse()
            for k in range(len(rows) - m, -1, -1):
                if rows[k:k + m] == key:
                    new = rows[k + m:]
                    if not new:
                        return 0
                    self.raw = self.raw[:-1] + new
                    return len(new) - 1
        return -1

'''.replace("\n", nl)
reps = [("    def _make(self):", "    def _make(self, count=None):"),
        ("ch.SetInputValue(4, self.page)", "ch.SetInputValue(4, count or self.page)"),
        ("    def ensure(self, min_ok, max_pages=40):", REFRESH + "    def ensure(self, min_ok, max_pages=40):")]
if "def refresh(" in t:
    print("이미 적용 - 건너뜀")
else:
    bad = [a for a, _ in reps if t.count(a) != 1]
    if bad:
        raise SystemExit(f"anchor 문제 {bad} - 중단 (파일 변경 없음)")
    p.with_suffix(".py.bak3").write_text(t, encoding="utf-8")
    for a, b in reps:
        t = t.replace(a, b)
    p.write_text(t, encoding="utf-8")
    print("chart_std: refresh() patched (백업 chart_std.py.bak3)")
py_compile.compile(str(p), doraise=True)
print("compile OK (64bit 문법)")
