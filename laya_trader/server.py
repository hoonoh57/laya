
import contextlib
import logging
import os

import uvicorn
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse

from . import config, ta
from .db import DB
from .engine import Engine
from .hub import Hub

ROOT = config.ROOT
(ROOT / "logs").mkdir(exist_ok=True)
(ROOT / "run").mkdir(exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s",
                    handlers=[logging.FileHandler(ROOT / "logs" / "server.log", encoding="utf-8")])

db = DB(ROOT / "data" / "app.db")
hub = Hub(db)
engine = Engine(db, hub)
SERVER = None


@contextlib.asynccontextmanager
async def lifespan(app):
    (ROOT / "run" / "server.pid").write_text(str(os.getpid()))
    await engine.start()
    yield
    await engine.stop()
    (ROOT / "run" / "server.pid").unlink(missing_ok=True)


app = FastAPI(lifespan=lifespan)


async def act(coro):
    try:
        return {"ok": True, "result": await coro}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/")
async def index():
    return FileResponse(ROOT / "laya_trader" / "static" / "desk.html")


@app.get("/classic")
async def classic():
    return FileResponse(ROOT / "laya_trader" / "static" / "index.html")


@app.get("/chart")
async def chart_page():
    return FileResponse(ROOT / "laya_trader" / "static" / "chart.html")


@app.get("/vendor/{name}")
async def vendor(name: str):
    f = ROOT / "laya_trader" / "static" / "vendor" / os.path.basename(name)
    if not f.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(f, media_type="text/css" if f.suffix == ".css" else "application/javascript")


@app.get("/api/health")
async def health():
    return {"ok": True, "mode": config.mode_label(), "status": engine.status}


@app.get("/api/state")
async def state():
    return engine.snapshot()


@app.post("/api/conditions/refresh")
async def cond_refresh():
    return await act(engine.refresh_conditions())


@app.post("/api/conditions/{seq}/subscribe")
async def cond_sub(seq: str):
    return await act(engine.subscribe_condition(seq))


@app.post("/api/conditions/{seq}/unsubscribe")
async def cond_unsub(seq: str):
    return await act(engine.unsubscribe_condition(seq))


@app.post("/api/watchlist")
async def watchlist(body: dict):
    return await act(engine.set_watchlist(body.get("codes", [])))


@app.post("/api/orderbook")
async def orderbook(body: dict):
    return await act(engine.set_orderbook(body.get("code", "")))


@app.post("/api/evaluate")
async def evaluate(body: dict):
    return await act(engine.evaluate(str(body["code"]).strip(), "manual", bool(body.get("order"))))


@app.post("/api/order")
async def order(body: dict):
    if body.get("side") not in ("buy", "sell"):
        raise HTTPException(400, "side는 buy/sell")
    return await act(engine.manual_order(body["side"], body["code"], body["qty"], body.get("price")))


@app.post("/api/balance")
async def balance():
    return await act(engine.refresh_balance_safe(force=True))


@app.post("/api/auto")
async def auto(body: dict):
    return await act(engine.set_auto(body.get("on")))


@app.post("/api/settings")
async def settings(body: dict):
    return await act(engine.update_settings(body))


@app.post("/api/mode")
async def mode(body: dict):
    mock = bool(body.get("mock"))
    if not mock and body.get("confirm") != "REAL":
        raise HTTPException(400, "실전 전환 확인값 누락")
    return await act(engine.switch_mode(mock))


@app.get("/api/bars")
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
    return await act(_get())


@app.get("/api/track")
async def track():
    """정밀 추적 상태: 전략(서버) + 브리지 tracker"""
    async def _get():
        r = {"strategy": engine.strategy.snapshot()}
        try:
            r["bridge"] = await engine.cybos.call("track_status")
        except Exception as e:
            r["bridge"] = {"error": str(e)}
        return r
    return await act(_get())


@app.post("/api/cybos/restart")
async def cybos_restart():
    return await act(engine.cybos.restart())


@app.post("/api/shutdown")
async def shutdown():
    if SERVER:
        SERVER.should_exit = True
    return {"ok": True}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    hub.clients.add(ws)
    try:
        await ws.send_json({"kind": "snapshot", "data": engine.snapshot()})
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        hub.clients.discard(ws)


def run():
    global SERVER
    cfg = uvicorn.Config(app, host=config.env("SERVER_HOST", "127.0.0.1"),
                         port=int(config.env("SERVER_PORT", "8755")), log_config=None)
    SERVER = uvicorn.Server(cfg)
    SERVER.run()
