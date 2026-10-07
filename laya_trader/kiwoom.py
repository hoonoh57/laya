"""키움 REST API. TRADING_MOCK에 따라 mockapi/api 도메인을 선택한다."""
import asyncio
import datetime as dt
import json
import logging
import time

import httpx
import websockets

log = logging.getLogger("kiwoom")


class KiwoomError(Exception):
    pass


def to_int(v):
    try:
        return int(float(str(v).replace(",", "").strip() or 0))
    except ValueError:
        return 0


def to_float(v):
    try:
        return float(str(v).replace(",", "").strip() or 0)
    except ValueError:
        return 0.0


def norm_code(c):
    c = str(c or "").strip()
    return c[1:] if len(c) == 7 and c[0].isalpha() else c


def round_tick(p):
    p = int(p)
    for limit, tick in ((2000, 1), (5000, 5), (20000, 10), (50000, 50), (200000, 100), (500000, 500)):
        if p < limit:
            return p // tick * tick
    return p // 1000 * 1000


class KiwoomREST:
    def __init__(self, appkey, secretkey, mock: bool):
        self.appkey, self.secretkey, self.mock = appkey, secretkey, mock
        host = "mockapi.kiwoom.com" if mock else "api.kiwoom.com"
        self.base = f"https://{host}"
        self.ws_url = f"wss://{host}:10000/api/dostk/websocket"
        self._http = httpx.AsyncClient(base_url=self.base, timeout=10)
        self._token, self._exp = None, 0.0
        self._last = {}

    async def aclose(self):
        await self._http.aclose()

    async def token(self, force=False):
        if self._token and not force and time.time() < self._exp - 300:
            return self._token
        r = await self._http.post("/oauth2/token", json={
            "grant_type": "client_credentials", "appkey": self.appkey, "secretkey": self.secretkey},
            headers={"Content-Type": "application/json;charset=UTF-8"})
        d = r.json()
        if str(d.get("return_code")) != "0" or not d.get("token"):
            raise KiwoomError(f"토큰 발급 실패: {d.get('return_msg', r.text[:200])}")
        self._token = d["token"]
        try:
            self._exp = dt.datetime.strptime(d.get("expires_dt", ""), "%Y%m%d%H%M%S").timestamp()
        except ValueError:
            self._exp = time.time() + 6 * 3600
        return self._token

    async def call(self, path, api_id, body, cont_yn="N", next_key="", _retry=True):
        wait = self._last.get(api_id, 0) + 0.35 - time.monotonic()   # 같은 TR 연속 호출 간격
        if wait > 0:
            await asyncio.sleep(wait)
        self._last[api_id] = time.monotonic()
        headers = {"Content-Type": "application/json;charset=UTF-8",
                   "authorization": f"Bearer {await self.token()}",
                   "api-id": api_id, "cont-yn": cont_yn, "next-key": next_key}
        r = await self._http.post(path, json=body, headers=headers)
        if r.status_code == 401 and _retry:
            await self.token(force=True)
            return await self.call(path, api_id, body, cont_yn, next_key, _retry=False)
        try:
            d = r.json()
        except ValueError:
            raise KiwoomError(f"{api_id}: HTTP {r.status_code} {r.text[:200]}")
        if r.status_code != 200 or str(d.get("return_code", "0")) != "0":
            raise KiwoomError(f"{api_id}: {d.get('return_msg', r.text[:200])}")
        return d

    async def balance(self):      # 계좌평가잔고내역
        return await self.call("/api/dostk/acnt", "kt00018", {"qry_tp": "1", "dmst_stex_tp": "KRX"})

    async def deposit(self):      # 예수금상세현황
        return await self.call("/api/dostk/acnt", "kt00001", {"qry_tp": "3"})

    async def order(self, side, code, qty, price=None):
        """price=None이면 시장가(trde_tp=3), 값이 있으면 보통 지정가(trde_tp=0)"""
        api_id = "kt10000" if side == "buy" else "kt10001"
        body = {"dmst_stex_tp": "KRX", "stk_cd": code, "ord_qty": str(int(qty)),
                "ord_uv": "" if price is None else str(int(price)),
                "trde_tp": "3" if price is None else "0", "cond_uv": ""}
        return await self.call("/api/dostk/ordr", api_id, body)


class KiwoomWS:
    """조건검색(CNSRLST/CNSRREQ/CNSRCLR)과 실시간(REG/REAL)을 처리하는 단일 웹소켓. 끊기면 자동 재연결"""
    def __init__(self, rest, on_message, on_status, on_login):
        self.rest, self.on_message, self.on_status, self.on_login = rest, on_message, on_status, on_login
        self.ws, self.connected, self._stop = None, False, False

    async def run(self):
        backoff = 2
        while not self._stop:
            reason = "연결 종료"
            try:
                token = await self.rest.token()
                async with websockets.connect(self.rest.ws_url, ping_interval=None,
                                              max_size=None, open_timeout=10) as ws:
                    self.ws = ws
                    await ws.send(json.dumps({"trnm": "LOGIN", "token": token}))
                    async for raw in ws:
                        msg = json.loads(raw)
                        trnm = msg.get("trnm")
                        if trnm == "PING":                     # 받은 그대로 돌려줘야 연결이 유지됨
                            await ws.send(raw if isinstance(raw, str) else raw.decode())
                            continue
                        if trnm == "LOGIN":
                            if str(msg.get("return_code")) != "0":
                                raise KiwoomError(f"웹소켓 로그인 실패: {msg.get('return_msg')}")
                            self.connected, backoff = True, 2
                            await self.on_status(True, "로그인 성공")
                            await self.on_login()
                            continue
                        try:
                            await self.on_message(msg)
                        except Exception:
                            log.exception("메시지 처리 오류: %s", str(msg)[:300])
            except asyncio.CancelledError:
                raise
            except Exception as e:
                reason = f"{type(e).__name__}: {e}"
            self.connected, self.ws = False, None
            if self._stop:
                break
            await self.on_status(False, f"{reason} → {backoff}초 후 재연결")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60)

    async def send(self, obj):
        if not self.ws or not self.connected:
            raise KiwoomError("키움 웹소켓 미연결")
        await self.ws.send(json.dumps(obj))

    async def close(self):
        self._stop = True
        if self.ws:
            await self.ws.close()
