import sys
p = r"cybos_bridge\cybos_bridge.py"
raw = open(p, encoding="utf-8-sig", newline="").read()
crlf = "\r\n" in raw
t = raw.replace("\r\n", "\n")
a1 = "import pythoncom\nimport win32com.client\n"
n1 = a1 + "import os\nsys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))\nfrom chart_std import ChartPager  # noqa: E402\n"
a2 = "        self.subs = {}\n"
n2 = a2 + "        self.pagers = {}\n"
a3 = "    def m_orderbook_snapshot(self, code):\n"
n3 = '''    def m_bars(self, code, kind="T", period=120, more=False, min_ok=0, reset=False):
        """표준화 봉(chart_std). more=True: +이전페이지 1회, min_ok: 완전봉 n개까지 자동, reset: 최신부터 다시"""
        self._need_conn()
        key = (plain(code), kind, int(period))
        p = None if reset else self.pagers.get(key)
        if p is None:
            p = ChartPager(self.cp, acode(code), kind, int(period))
            self.pagers.pop(key, None)
            self.pagers[key] = p
            while len(self.pagers) > 60:
                self.pagers.pop(next(iter(self.pagers)))
            self._wait_limit(); p.load_page()
        elif more and p.has_prev:
            self._wait_limit(); p.load_page()
        while min_ok and p.has_prev and p.pages < 40 and sum(1 for b in p.bars() if b["day_ok"]) < min_ok:
            self._wait_limit(); p.load_page()
        return {"code": plain(code), "kind": kind, "period": int(period), "base": p.base, "n": p.n,
                "has_prev": p.has_prev, "pages": p.pages, "bars": p.bars()}

''' + a3
for a in (a1, a2, a3):
    if t.count(a) != 1:
        print("anchor not found - 중단:", a.strip()); sys.exit(1)
t = t.replace(a1, n1).replace(a2, n2).replace(a3, n3)
if crlf:
    t = t.replace("\n", "\r\n")
open(p, "w", encoding="utf-8", newline="").write(t)
print("patched")
