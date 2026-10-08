"""cybos_bridge.py에 정밀 추적(tracker.py) 연결. 앵커가 모두 정확히 1개일 때만 쓴다. 이미 적용됐으면 건너뜀."""
import py_compile
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
f = ROOT / "cybos_bridge" / "cybos_bridge.py"
with open(f, encoding="utf-8", newline="") as fp:
    src = fp.read()
crlf = "\r\n" in src
t = src.replace("\r\n", "\n")

METHODS = '''    # ---------- 정밀 추적 (tracker.py) ----------
    def m_track_set(self, codes, kind="T", period=360, min_ok=300):
        # 추적 종목 전체 지정: 목록에 없는 종목은 해제, 새 종목은 초기 봉 수신 후 실시간 구독
        self._need_conn()
        return self.tracker.set(list(codes), kind, int(period), int(min_ok))

    def m_track_status(self):
        return self.tracker.status()

    def m_track_bars(self, code):
        return self.tracker.bars(code)

    def m_track_clear(self):
        self.tracker.clear()
        return {"tracking": []}

'''
LOOP = '''        try:
            cy.tracker.tick()
        except Exception:
            if time.time() - getattr(cy, "_terr", 0) > 10:
                cy._terr = time.time()
                log("tracker error", traceback.format_exc())
'''
P = [
    ("import", 'from chart_std import ChartPager  # noqa: E402\n',
     'from chart_std import ChartPager  # noqa: E402\nfrom tracker import Tracker  # noqa: E402\n'),
    ("init", '        self.pagers = {}\n',
     '        self.pagers = {}\n        self.tracker = Tracker(self.cp, self.codemgr, broadcast, log)\n'),
    ("status", '"python": sys.version, "subscriptions": list(self.subs)}',
     '"python": sys.version, "subscriptions": list(self.subs),\n                "tracking": list(self.tracker.items)}'),
    ("unsub_all", '            self.m_unsubscribe_orderbook(code)\n        return {"ok": True}',
     '            self.m_unsubscribe_orderbook(code)\n        self.tracker.clear()\n        return {"ok": True}'),
    ("methods", '    def m_name(self, code):\n', METHODS + '    def m_name(self, code):\n'),
    ("loop", '        if time.time() - last_check > 5:\n', LOOP + '        if time.time() - last_check > 5:\n'),
]

if "from tracker import Tracker" in t:
    print("bridge: 이미 적용됨 (건너뜀)")
else:
    bad = [(n, t.count(o)) for n, o, _ in P if t.count(o) != 1]
    if bad:
        raise SystemExit(f"anchor 불일치 - 중단 (파일 변경 없음): {bad}")
    for _, o, n in P:
        t = t.replace(o, n)
    bak = f.with_name(f.name + ".bak_track")
    if not bak.exists():
        shutil.copy2(f, bak)
    with open(f, "w", encoding="utf-8", newline="") as fp:
        fp.write(t.replace("\n", "\r\n") if crlf else t)
    print(f"bridge patched (백업 {bak.name})")
py_compile.compile(str(f), doraise=True)
print("compile OK")
for i, line in enumerate(open(f, encoding="utf-8"), 1):
    if "tracker" in line.lower():
        print(f"{i:5}: {line.strip()}")
