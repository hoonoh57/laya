"""engine.py / server.py / settings.yaml 에 strategy.py 연결 + Laya 워밍업 + GET /api/track.
앵커가 모두 정확히 1줄일 때만 쓴다. 이미 적용됐으면 건너뜀."""
import py_compile
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(p):
    with open(p, encoding="utf-8", newline="") as fp:
        s = fp.read()
    return s.replace("\r\n", "\n"), "\r\n" in s


def save(p, t, crlf):
    with open(p, "w", encoding="utf-8", newline="") as fp:
        fp.write(t.replace("\n", "\r\n") if crlf else t)


def apply(t, ops):
    lines = t.split("\n")
    bad = []
    for name, _, anchor, _ in ops:
        n = sum(1 for x in lines if anchor in x)
        if n != 1:
            bad.append((name, n))
    if bad:
        return None, bad
    for name, mode, anchor, new in ops:
        i = next(k for k, x in enumerate(lines) if anchor in x)
        ind = lines[i][: len(lines[i]) - len(lines[i].lstrip())]
        if mode == "sub":
            lines[i] = lines[i].replace(anchor, new)
            continue
        add = [(ind + x) if x else x for x in new]
        if mode == "after":
            lines[i + 1:i + 1] = add
        elif mode == "before":
            lines[i:i] = add
        else:
            lines[i:i + 1] = add
    return "\n".join(lines), []


ENGINE = [
    ("import_time", "after", "import logging", ["import time"]),
    ("import_strategy", "after", "from .cybos_client import CybosBridge", ["from .strategy import Strategy"]),
    ("init", "after", "self.tasks = []",
     ["self.orderbooks = {}", "self._laya_warm_ms = 0.0", "self.strategy = Strategy(self)"]),
    ("snap_settings", "sub", '"settings": {k: self.cfg.get(k) for k in ("gate", "risk", "engine")},',
     '"settings": {k: self.cfg.get(k) for k in ("gate", "risk", "engine", "track")}, "track": self.strategy.snapshot(),'),
    ("snap_events", "sub", '("decision", "condition_hit", "order", "exec", "log")',
     '("decision", "condition_hit", "order", "exec", "log", "signal", "signal_outcome")'),
    ("warmup", "replace", 'return LayaGate(self.cfg["laya"])',
     ['g = LayaGate(self.cfg["laya"])',
      "from .laya_judge import Judge",
      "t0 = time.perf_counter()",
      'Judge(g)({"symbol": "warmup", "signal": "warmup"})  # 첫 판단 GPU 적재(약 7초)를 시작 시 미리',
      "self._laya_warm_ms = (time.perf_counter() - t0) * 1000",
      "return g"]),
    ("ready_log", "after", 'self.status["laya"] = "ready"',
     ['await self.log(f"Laya 준비 완료 (워밍업 {self._laya_warm_ms:.0f}ms)")']),
    ("cybos_status", "after", "async def _on_cybos_status(self, connected, msg):",
     ["    self.strategy.sent = None  # 브리지 재연결/종료: 추적 목록 다시 전송 (진입 기록은 유지)"]),
    ("cybos_event", "after", "async def _on_cybos_event(self, msg):",
     ['    ev = msg.get("event")',
      '    if ev in ("bar_live", "bar_close", "track_reset"):',
      "        await self.strategy.on_event(msg)",
      "        return",
      '    if ev == "orderbook" and (msg.get("data") or {}).get("code"):',
      '        self.orderbooks[msg["data"]["code"]] = msg["data"]']),
    ("quote_sync", "after", 'await self.hub.emit("quotes", r["rows"], store=False)',
     ['asyncio.create_task(self._track_sync(r["rows"]))']),
    ("track_sync", "before", "async def set_watchlist(self, codes):",
     ["async def _track_sync(self, rows):",
      "    try:",
      "        await self.strategy.sync(rows)",
      "        for c in list(self.strategy.sent or []):",
      "            if c not in self.strategy.books:",
      "                await self.strategy._load(c)",
      '        self._last_err.pop("track", None)',
      "    except Exception as e:",
      '        await self.log_once("track", f"정밀 추적 동기화 실패: {e}")',
      ""]),
    ("insert_skip", "before", "asyncio.create_task(self.evaluate(code, seq))",
     ['if self.strategy.cfg().get("enabled"):',
      "    return  # 정밀 추적 전략 ON: 일봉 즉시평가 생략(GPU 동시 사용 방지)"]),
    ("upd_patch", "sub", 'if k in ("gate", "risk", "engine")}', 'if k in ("gate", "risk", "engine", "track")}'),
    ("upd_ret", "sub", 'return {k: self.cfg[k] for k in ("gate", "risk", "engine")}',
     'return {k: self.cfg.get(k) for k in ("gate", "risk", "engine", "track")}'),
]
SERVER = [
    ("api_track", "before", '@app.post("/api/cybos/restart")',
     ['@app.get("/api/track")',
      "async def track():",
      '    """정밀 추적 상태: 전략(서버) + 브리지 tracker"""',
      "    async def _get():",
      '        r = {"strategy": engine.strategy.snapshot()}',
      "        try:",
      '            r["bridge"] = await engine.cybos.call("track_status")',
      "        except Exception as e:",
      '            r["bridge"] = {"error": str(e)}',
      "        return r",
      "    return await act(_get())",
      "",
      ""]),
]
YAML_TRACK = """track:
  enabled: false                 # 정밀 추적 전략 ON/OFF (UI 설정으로 변경)
  kind: T
  period: 360
  min_open_pct: 2.0              # 추적/진입: 시가대비 하한(%)
  max_open_pct: 20.0             # 추적/진입: 시가대비 상한(%)
  track_start: "09:00"
  track_end: "15:20"
  entry_start: "09:00"           # 기준 진입 허용 시간대
  entry_end: "10:30"
  release_gap: 1.0               # 하한 - 1%p 미만이
  release_sec: 30                # 30초 지속되면 추적 해제
  max_n: 20
  p_min: 0.6
  first_only: true               # 하루 첫 정규장 상승전환만 기준 진입 후보
"""

eng_p = ROOT / "laya_trader" / "engine.py"
srv_p = ROOT / "laya_trader" / "server.py"
yml_p = ROOT / "config" / "settings.yaml"
et, ec = load(eng_p)
st, sc = load(srv_p)
done = "from .strategy import Strategy" in et
if done:
    print("engine/server: 이미 적용됨 (건너뜀)")
else:
    e2, eb = apply(et, ENGINE)
    s2, sb = (st, []) if "/api/track" in st else apply(st, SERVER)
    if eb or sb:
        raise SystemExit(f"anchor 불일치 - 중단 (파일 변경 없음): engine={eb} server={sb}")
    for p in (eng_p, srv_p):
        bak = p.with_name(p.name + ".bak_strat")
        if not bak.exists():
            shutil.copy2(p, bak)
    save(eng_p, e2, ec)
    save(srv_p, s2, sc)
    print("engine.py / server.py patched (백업 *.bak_strat)")
yt, yc = load(yml_p)
if "\ntrack:" not in "\n" + yt:
    save(yml_p, yt.rstrip("\n") + "\n" + YAML_TRACK, yc)
    print("settings.yaml: track 항목 추가")
else:
    print("settings.yaml: track 이미 있음")
for p in (eng_p, srv_p):
    py_compile.compile(str(p), doraise=True)
print("compile OK")
for i, line in enumerate(open(eng_p, encoding="utf-8"), 1):
    if any(k in line for k in ("strategy", "_track_sync", "warm", "orderbooks")):
        print(f"{i:5}: {line.rstrip()[:110]}")
