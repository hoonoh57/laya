"""Cybos Plus(CREON) 32비트 브리지.
실행: E:\\Python310-32\\python.exe cybos_bridge.py <port> <parent_pid>
프로토콜: 줄 단위 JSON  요청 {"id","method","params"} / 응답 {"id","ok","result|error"} / 푸시 {"event","data"}
COM은 반드시 메인 스레드에서만 호출한다(STA)."""
import ctypes, json, queue, socket, sys, threading, time, traceback

import pythoncom
import win32com.client

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8801
PARENT_PID = int(sys.argv[2]) if len(sys.argv) > 2 else 0

req_q = queue.Queue()
clients, clients_lock = [], threading.Lock()


def log(*a):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)


def send(conn, obj):
    try:
        conn.sendall((json.dumps(obj, ensure_ascii=False, default=str) + "\n").encode("utf-8"))
    except OSError:
        pass


def broadcast(obj):
    with clients_lock:
        cs = list(clients)
    for c in cs:
        send(c, obj)


def client_reader(conn):
    buf = b""
    try:
        while True:
            chunk = conn.recv(65536)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if line.strip():
                    req_q.put((conn, json.loads(line.decode("utf-8"))))
    except (OSError, ValueError) as e:
        log("client error:", e)
    finally:
        with clients_lock:
            if conn in clients:
                clients.remove(conn)
        conn.close()


def accept_loop(srv):
    while True:
        conn, _ = srv.accept()
        with clients_lock:
            clients.append(conn)
        threading.Thread(target=client_reader, args=(conn,), daemon=True).start()


def parent_alive():
    if not PARENT_PID:
        return True
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x00100000, False, PARENT_PID)  # SYNCHRONIZE
    if not h:
        return False
    r = k32.WaitForSingleObject(h, 0)
    k32.CloseHandle(h)
    return r != 0  # 0 = 종료됨


def acode(c):
    c = str(c).strip()
    return c if c[:1].isalpha() else "A" + c


def plain(c):
    c = str(c).strip()
    return c[1:] if len(c) == 7 and c[0].isalpha() else c


MARKETEYE_FIELDS = {0: "code", 1: "time", 2: "sign", 3: "diff", 4: "price", 5: "open",
                    6: "high", 7: "low", 8: "ask", 9: "bid", 10: "volume", 11: "value", 17: "name"}


class OrderbookHandler:
    """Dscbo1.StockJpBid 실시간 이벤트. 헤더 3~22: 1~5호가, 23/24: 총잔량, 27~46: 6~10호가"""
    def init(self, obj, code):
        self.obj, self.code = obj, code

    def OnReceived(self):
        o = self.obj
        asks, bids = [], []
        for i in range(10):
            b = 3 + i * 4 if i < 5 else 27 + (i - 5) * 4
            asks.append({"price": o.GetHeaderValue(b), "qty": o.GetHeaderValue(b + 2)})
            bids.append({"price": o.GetHeaderValue(b + 1), "qty": o.GetHeaderValue(b + 3)})
        broadcast({"event": "orderbook", "data": {
            "code": plain(o.GetHeaderValue(0)), "time": o.GetHeaderValue(1),
            "asks": asks, "bids": bids,
            "total_ask": o.GetHeaderValue(23), "total_bid": o.GetHeaderValue(24), "realtime": True}})


class Cybos:
    def __init__(self):
        self.cp = win32com.client.Dispatch("CpUtil.CpCybos")
        self.codemgr = win32com.client.Dispatch("CpUtil.CpCodeMgr")
        self.subs = {}

    def handle(self, method, params):
        fn = getattr(self, "m_" + method, None)
        if fn is None:
            raise ValueError(f"unknown method: {method}")
        return fn(**params)

    def _need_conn(self):
        if not self.cp.IsConnect:
            raise RuntimeError("CREON Plus 미연결 (CREON 로그인 필요)")

    def _wait_limit(self):
        # 시세 조회 제한(LT_NONTRADE_REQUEST=1). 남은 횟수가 없으면 메시지를 펌프하며 대기
        while self.cp.GetLimitRemainCount(1) <= 0:
            end = time.time() + self.cp.LimitRequestRemainTime / 1000 + 0.05
            while time.time() < end:
                pythoncom.PumpWaitingMessages()
                time.sleep(0.01)

    def _request(self, obj):
        self._wait_limit()
        obj.BlockRequest()
        if obj.GetDibStatus() != 0:
            raise RuntimeError(f"Cybos 오류: {obj.GetDibMsg1()}")

    def m_status(self):
        return {"connected": bool(self.cp.IsConnect), "server_type": self.cp.ServerType,
                "admin": bool(ctypes.windll.shell32.IsUserAnAdmin()),
                "python": sys.version, "subscriptions": list(self.subs)}

    def m_marketeye(self, codes):
        self._need_conn()
        fields = sorted(MARKETEYE_FIELDS)
        rows = []
        for i in range(0, len(codes), 200):          # MarketEye는 1회 최대 200종목
            o = win32com.client.Dispatch("CpSysDib.MarketEye")
            o.SetInputValue(0, fields)
            o.SetInputValue(1, [acode(c) for c in codes[i:i + 200]])
            self._request(o)
            for j in range(o.GetHeaderValue(2)):
                r = {MARKETEYE_FIELDS[f]: o.GetDataValue(k, j) for k, f in enumerate(fields)}
                r["code"] = plain(r["code"])
                s = chr(r["sign"]) if isinstance(r["sign"], int) else str(r["sign"])
                diff = abs(r["diff"]) * (-1 if s in ("4", "5") else 1)   # 4: 하한, 5: 하락
                prev = r["price"] - diff
                r["diff"], r["sign"] = diff, s
                r["rate"] = round(diff / prev * 100, 2) if prev else 0.0
                rows.append(r)
        return {"rows": rows}

    def m_chart(self, code, count=120, period="D"):
        self._need_conn()
        o = win32com.client.Dispatch("CpSysDib.StockChart")
        o.SetInputValue(0, acode(code))
        o.SetInputValue(1, ord("2"))                 # 개수 기준
        o.SetInputValue(4, int(count))
        o.SetInputValue(5, [0, 2, 3, 4, 5, 8])       # 날짜, 시가, 고가, 저가, 종가, 거래량
        o.SetInputValue(6, ord(period))
        o.SetInputValue(9, ord("1"))                 # 수정주가
        self._request(o)
        n = o.GetHeaderValue(3)
        rows = [{"date": o.GetDataValue(0, i), "open": o.GetDataValue(1, i), "high": o.GetDataValue(2, i),
                 "low": o.GetDataValue(3, i), "close": o.GetDataValue(4, i), "volume": o.GetDataValue(5, i)}
                for i in range(n)]
        rows.reverse()                               # 과거 → 최근
        return {"code": plain(code), "rows": rows}

    def m_orderbook_snapshot(self, code):
        self._need_conn()
        o = win32com.client.Dispatch("Dscbo1.StockJpBid2")
        o.SetInputValue(0, acode(code))
        self._request(o)
        return {"code": plain(code), "time": o.GetHeaderValue(3),
                "asks": [{"price": o.GetDataValue(0, i), "qty": o.GetDataValue(2, i)} for i in range(10)],
                "bids": [{"price": o.GetDataValue(1, i), "qty": o.GetDataValue(3, i)} for i in range(10)],
                "total_ask": o.GetHeaderValue(4), "total_bid": o.GetHeaderValue(6), "realtime": False}

    def m_subscribe_orderbook(self, code):
        self._need_conn()
        code = plain(code)
        if code in self.subs:
            return {"subscribed": code}
        o = win32com.client.Dispatch("Dscbo1.StockJpBid")
        h = win32com.client.WithEvents(o, OrderbookHandler)
        h.init(o, code)
        o.SetInputValue(0, acode(code))
        o.Subscribe()
        self.subs[code] = (o, h)
        return {"subscribed": code}

    def m_unsubscribe_orderbook(self, code):
        item = self.subs.pop(plain(code), None)
        if item:
            item[0].Unsubscribe()
        return {"unsubscribed": plain(code)}

    def m_unsubscribe_all(self):
        for code in list(self.subs):
            self.m_unsubscribe_orderbook(code)
        return {"ok": True}

    def m_name(self, code):
        return {"code": plain(code), "name": self.codemgr.CodeToName(acode(code))}


def main():
    pythoncom.CoInitialize()
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)   # 중복 실행 방지
    try:
        srv.bind(("127.0.0.1", PORT))
    except OSError as e:
        log(f"포트 {PORT} 사용 중 - 이미 실행 중인 브리지가 있습니다: {e}")
        sys.exit(2)
    srv.listen(4)
    cy = Cybos()
    log(f"bridge ready port={PORT} admin={bool(ctypes.windll.shell32.IsUserAnAdmin())} "
        f"creon_connected={bool(cy.cp.IsConnect)}")
    threading.Thread(target=accept_loop, args=(srv,), daemon=True).start()

    last_check = time.time()
    while True:
        pythoncom.PumpWaitingMessages()
        try:
            conn, msg = req_q.get(timeout=0.005)
        except queue.Empty:
            msg = None
        if msg is not None:
            rid = msg.get("id")
            try:
                send(conn, {"id": rid, "ok": True, "result": cy.handle(msg["method"], msg.get("params") or {})})
            except Exception as e:
                log("error", msg.get("method"), traceback.format_exc())
                send(conn, {"id": rid, "ok": False, "error": f"{type(e).__name__}: {e}"})
        if time.time() - last_check > 5:
            last_check = time.time()
            if not parent_alive():
                log("부모 프로세스 종료 감지 → 브리지 종료")
                break
    try:
        cy.m_unsubscribe_all()
    except Exception:
        pass


if __name__ == "__main__":
    main()
