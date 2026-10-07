import datetime as dt
import json
import math


def _clean(o):
    if isinstance(o, float):
        return None if math.isnan(o) or math.isinf(o) else o
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    return o


class Hub:
    """브라우저 WebSocket 브로드캐스트 + 이벤트 저장"""
    def __init__(self, db):
        self.db, self.clients = db, set()

    async def emit(self, kind, data, store=True):
        data = _clean(data)
        ev = self.db.add_event(kind, data) if store else {
            "id": 0, "ts": dt.datetime.now().isoformat(timespec="seconds"), "kind": kind, "data": data}
        text = json.dumps(ev, ensure_ascii=False, default=str)
        for ws in list(self.clients):
            try:
                await ws.send_text(text)
            except Exception:
                self.clients.discard(ws)
