import asyncio
import contextlib
import datetime as dt
import logging

import pandas as pd

from . import config
from .cybos_client import CybosBridge
from .kiwoom import KiwoomREST, KiwoomWS, norm_code, round_tick, to_float, to_int
from src.indicators import compute_indicators
from src.sizing import decide_order
from src.state_builder import build_state

log = logging.getLogger("engine")


def deep_merge(a, b):
    out = dict(a or {})
    for k, v in (b or {}).items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


class Engine:
    def __init__(self, db, hub):
        self.db, self.hub = db, hub
        self.cfg = deep_merge(config.load_yaml(), db.get("settings", {}))
        self.gate = None
        self.kiwoom = self.kws = self.kws_task = None
        self.cybos = CybosBridge(config.env("CYBOS_PYTHON"), int(config.env("BRIDGE_PORT", "8801")),
                                 self._on_cybos_event, self._on_cybos_status)
        self.status = {"kiwoom_ws": False, "kiwoom_msg": "대기", "cybos": False,
                       "cybos_login": False, "cybos_msg": "대기", "laya": "loading"}
        self.conditions = []
        self.active = set()  # 실시간 구독은 사용자가 UI에서 직접 선택
        self.watchlist = db.get("watchlist", [])
        self.orderbook_code = db.get("orderbook_code", "")
        self.auto_trade = bool(db.get("auto_trade", False))
        self.account = {"equity": 0, "orderable": 0, "total_pl": 0, "holdings": [], "updated": None}
        self.eval_sem = asyncio.Semaphore(1)
        self._bal_lock = asyncio.Lock()
        self._bal_next = 0.0
        self._bal_pending = False
        self._bal_err_at = -1e9
        self._last_err = {}
        self.tasks = []

    # ---------- 공통 ----------
    def _mode(self):
        return "mock" if config.is_mock() else "real"

    def _today(self):
        return dt.date.today().strftime("%Y%m%d")

    def _cname(self, seq):
        return next((c["name"] for c in self.conditions if c["seq"] == seq), seq)

    async def push_status(self):
        await self.hub.emit("status", self.status, store=False)

    async def log(self, msg, level="info"):
        (log.error if level == "error" else log.info)(msg)
        await self.hub.emit("log", {"level": level, "msg": msg})

    async def log_once(self, key, msg):
        if self._last_err.get(key) != msg:
            self._last_err[key] = msg
            await self.log(msg, "error")

    def snapshot(self):
        return {"mock": config.is_mock(), "status": self.status, "auto_trade": self.auto_trade,
                "conditions": self.conditions, "active": sorted(self.active),
                "watchlist": self.watchlist, "orderbook_code": self.orderbook_code,
                "account": self.account,
                "settings": {k: self.cfg.get(k) for k in ("gate", "risk", "engine")},
                "events": {k: self.db.events(k, 100) for k in ("decision", "condition_hit", "order", "exec", "log")}}

    # ---------- 시작/종료 ----------
    async def start(self):
        self.tasks = [asyncio.create_task(c) for c in (
            self._load_laya(), self.cybos.run(), self._cybos_watch(), self._quote_loop(), self._balance_loop())]
        await self.start_kiwoom()
        await self.log(f"서버 시작 - {config.mode_label()}투자 모드, 자동매매 {'ON' if self.auto_trade else 'OFF'}")

    async def stop(self):
        for t in self.tasks:
            t.cancel()
        await self.stop_kiwoom()
        await self.cybos.stop()

    async def _load_laya(self):
        def _make():
            from src.laya_gate import LayaGate
            return LayaGate(self.cfg["laya"])
        try:
            self.gate = await asyncio.to_thread(_make)
            self.status["laya"] = "ready"
        except Exception as e:
            self.status["laya"] = f"error: {e}"
            log.exception("Laya load")
        await self.push_status()


    # ---------- 키움 ----------
    async def start_kiwoom(self):
        await self.stop_kiwoom()
        c = config.kiwoom_creds()
        if not c["appkey"] or not c["secretkey"]:
            self.status.update(kiwoom_ws=False, kiwoom_msg=f".env에 {config.mode_label()}투자 앱키/시크릿키가 없습니다")
            await self.push_status()
            return
        self.kiwoom = KiwoomREST(c["appkey"], c["secretkey"], c["mock"])
        self.kws = KiwoomWS(self.kiwoom, self._on_kiwoom_msg, self._on_kiwoom_status, self._on_kiwoom_login)
        self.kws_task = asyncio.create_task(self.kws.run())

    async def stop_kiwoom(self):
        if self.kws:
            await self.kws.close()
        if self.kws_task:
            self.kws_task.cancel()
            with contextlib.suppress(BaseException):
                await self.kws_task
        if self.kiwoom:
            await self.kiwoom.aclose()
        self.kiwoom = self.kws = self.kws_task = None
        self.conditions = []

    async def _on_kiwoom_status(self, ok, msg):
        self.status.update(kiwoom_ws=ok, kiwoom_msg=f"[{config.mode_label()}] {msg}")
        await self.push_status()

    async def _on_kiwoom_login(self):
        self.active.clear()
        self.db.set("active_conditions", [])
        await self.kws.send({"trnm": "CNSRLST"})
        await self.kws.send({"trnm": "REG", "grp_no": "1", "refresh": "1",
                             "data": [{"item": [""], "type": ["00", "04"]}]})   # 주문체결, 잔고
        asyncio.create_task(self.refresh_balance_safe())

    async def emit_conditions(self):
        await self.hub.emit("conditions", {"list": self.conditions, "active": sorted(self.active)}, store=False)

    async def _on_kiwoom_msg(self, msg):
        trnm, rc = msg.get("trnm"), str(msg.get("return_code", "0"))
        if trnm == "CNSRLST":
            self.conditions = [{"seq": str(r[0]).strip(), "name": r[1]} for r in (msg.get("data") or [])]
            await self.emit_conditions()
            await self.emit_conditions()
        elif trnm == "CNSRREQ":
            seq = str(msg.get("seq", "")).strip()
            if rc != "0":
                await self.log(f"조건 [{self._cname(seq)}] 요청 실패: {msg.get('return_msg')}", "error")
                self.active.discard(seq)
                self.db.set("active_conditions", sorted(self.active))
                await self.emit_conditions()
                return
            codes = [norm_code(x.get("jmcode") or x.get("9001")) for x in (msg.get("data") or []) if isinstance(x, dict)]
            await self.hub.emit("condition_hit", {"seq": seq, "name": self._cname(seq), "type": "초기",
                                                  "codes": codes[:50], "count": len(codes)})
            if self.cfg["engine"].get("eval_initial_hits"):
                for c in codes:
                    await self._on_insert(c, seq)
        elif trnm == "CNSRCLR":
            await self.log(f"조건 실시간 해제: {self._cname(str(msg.get('seq', '')))}")
        elif trnm == "REG" and rc != "0":
            await self.log(f"실시간 등록 실패: {msg.get('return_msg')}", "error")
        elif trnm == "REAL":
            for it in msg.get("data") or []:
                typ, v = it.get("type"), it.get("values") or {}
                if typ == "02":                                         # 조건검색 실시간
                    code = norm_code(v.get("9001") or it.get("item"))
                    seq, flag = str(v.get("841", "")).strip(), v.get("843", "")
                    await self.hub.emit("condition_hit", {"seq": seq, "name": self._cname(seq),
                                                          "type": "편입" if flag == "I" else "이탈",
                                                          "codes": [code], "count": 1})
                    if flag == "I":
                        await self._on_insert(code, seq)
                elif typ == "00":                                       # 주문체결
                    await self.hub.emit("exec", {
                        "code": norm_code(v.get("9001")), "name": v.get("302", ""), "status": v.get("913", ""),
                        "side": v.get("905", ""), "ord_no": v.get("9203", ""), "ord_qty": v.get("900", ""),
                        "exec_price": abs(to_int(v.get("910"))), "exec_qty": v.get("911", "")})
                    asyncio.create_task(self.refresh_balance_safe())
                elif typ == "04":
                    asyncio.create_task(self.refresh_balance_safe())

    async def _cnsr_req(self, seq):
        await self.kws.send({"trnm": "CNSRREQ", "seq": seq, "search_type": "1", "stex_tp": "K"})

    async def subscribe_condition(self, seq):
        if not self.kws or not self.kws.connected:
            raise RuntimeError("키움 웹소켓 미연결")
        if seq in self.active:
            return
        await self._cnsr_req(seq)
        self.active.add(seq)
        self.db.set("active_conditions", sorted(self.active))
        await self.emit_conditions()

    async def unsubscribe_condition(self, seq):
        if self.kws and self.kws.connected:
            await self.kws.send({"trnm": "CNSRCLR", "seq": seq})
        self.active.discard(seq)
        self.db.set("active_conditions", sorted(self.active))
        await self.emit_conditions()

    async def refresh_conditions(self):
        if not self.kws or not self.kws.connected:
            raise RuntimeError("키움 웹소켓 미연결")
        await self.kws.send({"trnm": "CNSRLST"})

    # ---------- 계좌 ----------
    async def refresh_balance(self):
        if not self.kiwoom:
            return
        async with self._bal_lock:
            b = await self.kiwoom.balance()
            d = await self.kiwoom.deposit()
            holdings = []
            for h in b.get("acnt_evlt_remn_indv_tot") or []:
                qty = to_int(h.get("rmnd_qty"))
                if qty > 0:
                    holdings.append({"code": norm_code(h.get("stk_cd")), "name": h.get("stk_nm", ""), "qty": qty,
                                     "avg": abs(to_int(h.get("pur_pric"))), "cur": abs(to_int(h.get("cur_prc"))),
                                     "pl": to_int(h.get("evltv_prft")), "rate": to_float(h.get("prft_rt"))})
            equity = to_int(b.get("prsm_dpst_aset_amt"))
            day_key = f"day_start_equity:{self._mode()}:{self._today()}"
            if equity > 0 and not self.db.get(day_key):
                self.db.set(day_key, equity)
            self.account = {"equity": equity, "orderable": to_int(d.get("ord_alow_amt")),
                            "total_pl": to_int(b.get("tot_evlt_pl")), "holdings": holdings,
                            "updated": dt.datetime.now().strftime("%H:%M:%S")}
            await self.hub.emit("account", self.account, store=False)

    async def refresh_balance_safe(self, force=False):
        """키움 호출 최소화: 최소 간격 + 1700 오류 시 60초 정지 + 같은 오류 로그 5분 1회"""
        now = asyncio.get_running_loop().time()
        if self._bal_lock.locked() or (not force and now < self._bal_next):
            self._bal_pending = True
            return
        try:
            await self.refresh_balance()
            self._bal_next = now + float(self.cfg["engine"].get("balance_min_gap_sec", 5))
        except Exception as e:
            backoff = 60 if "1700" in str(e) else 10
            self._bal_next = now + backoff
            self._bal_pending = True
            if now - self._bal_err_at > 300:
                self._bal_err_at = now
                await self.log(f"잔고 조회 실패({backoff}초 후 재시도, 5분간 같은 오류 생략): {e}", "error")

    async def _balance_loop(self):
        """주기 조회 없음. 이벤트로 쌓인 요청만 간격을 지켜 1회 처리"""
        while True:
            await asyncio.sleep(1)
            if self._bal_pending and self.kws and self.kws.connected:
                if asyncio.get_running_loop().time() >= self._bal_next:
                    self._bal_pending = False
                    await self.refresh_balance_safe()

    def portfolio(self):
        eq = self.account["equity"]
        start = self.db.get(f"day_start_equity:{self._mode()}:{self._today()}") or eq
        return {"daily_pnl_pct": (eq - start) / start if start else 0.0,
                "open_positions": len(self.account["holdings"])}

    # ---------- Cybos ----------
    async def _on_cybos_status(self, connected, msg):
        self.status.update(cybos=connected, cybos_login=False, cybos_msg=msg)
        await self.push_status()
        if connected:
            asyncio.create_task(self._cybos_check())   # 읽기 루프가 시작된 뒤 호출되도록 별도 태스크로

    async def _cybos_check(self):
        try:
            st = await self.cybos.call("status")
        except Exception as e:
            self.status["cybos_msg"] = str(e)
            await self.push_status()
            return
        was = self.status["cybos_login"]
        self.status["cybos_login"] = bool(st.get("connected"))
        msg = "정상" if st.get("connected") else "CREON Plus 로그인 필요"
        if not st.get("admin"):
            msg += " / 관리자 권한 아님"
        changed = was != self.status["cybos_login"] or msg != self.status["cybos_msg"]
        self.status["cybos_msg"] = msg
        if self.status["cybos_login"] and not was and self.orderbook_code:
            try:
                await self._subscribe_ob(self.orderbook_code)
            except Exception as e:
                await self.log_once("ob", f"호가 구독 실패: {e}")
        if changed:
            await self.push_status()


    async def _cybos_watch(self):
        while True:
            await asyncio.sleep(10)
            if self.cybos.connected:
                await self._cybos_check()

    async def _subscribe_ob(self, code):
        snap = await self.cybos.call("orderbook_snapshot", code=code)
        await self.hub.emit("orderbook", snap, store=False)
        await self.cybos.call("subscribe_orderbook", code=code)

    async def set_orderbook(self, code):
        code = norm_code(code)
        if self.orderbook_code and self.orderbook_code != code and self.cybos.connected:
            with contextlib.suppress(Exception):
                await self.cybos.call("unsubscribe_orderbook", code=self.orderbook_code)
        self.orderbook_code = code
        self.db.set("orderbook_code", code)
        if code:
            await self._subscribe_ob(code)

    async def _on_cybos_event(self, msg):
        if msg.get("event") == "orderbook":
            await self.hub.emit("orderbook", msg["data"], store=False)

    async def _quote_loop(self):
        while True:
            await asyncio.sleep(float(self.cfg["engine"].get("quote_interval_sec", 3)))
            if not (self.status["cybos_login"] and self.watchlist):
                continue
            try:
                r = await self.cybos.call("marketeye", codes=self.watchlist[:200])
                await self.hub.emit("quotes", r["rows"], store=False)
                self._last_err.pop("quote", None)
            except Exception as e:
                await self.log_once("quote", f"MarketEye 실패: {e}")

    async def set_watchlist(self, codes):
        out = []
        for c in codes:
            c = norm_code(c)
            if len(c) == 6 and c.isalnum() and c not in out:
                out.append(c)
        self.watchlist = out[:200]
        self.db.set("watchlist", self.watchlist)
        return self.watchlist

    # ---------- 판단 + 주문 ----------
    async def _on_insert(self, code, seq):
        if not code:
            return
        if code not in self.watchlist and len(self.watchlist) < 200:
            self.watchlist.append(code)
            self.db.set("watchlist", self.watchlist)
        asyncio.create_task(self.evaluate(code, seq))

    async def evaluate(self, code, seq="manual", force_order=False):
        async with self.eval_sem:
            try:
                if self.gate is None:
                    raise RuntimeError("Laya 모델 로딩 전")
                if not self.status["cybos_login"]:
                    raise RuntimeError("Cybos 미연결")
                if any(h["code"] == code for h in self.account["holdings"]):
                    await self.log(f"{code} 이미 보유 중 - 평가 생략")
                    return
                ch = await self.cybos.call("chart", code=code, count=int(self.cfg["engine"]["chart_bars"]))
                df = pd.DataFrame(ch["rows"])
                if len(df) < 60:
                    raise RuntimeError(f"일봉 부족({len(df)}개)")
                q = (await self.cybos.call("marketeye", codes=[code]))["rows"][0]
                df.loc[df.index[-1], "close"] = q["price"]           # 장중 현재가 반영
                ind = compute_indicators(df)
                state = build_state(code, "long", ind, [], f"kiwoom_condition:{self._cname(seq)}")
                g = await asyncio.to_thread(self.gate.evaluate, state)
                d = decide_order(g, self.cfg["gate"], self.cfg["risk"], self.portfolio())
                rec = {"code": code, "name": q.get("name", ""), "condition": self._cname(seq),
                       "price": q["price"], "indicators": ind, "p_entry": round(g.p_entry, 3),
                       "conf": round(g.entry_confidence, 3), "regime": g.regime,
                       "news_risk": round(g.p_news_risk, 3), "conviction": round(g.conviction, 2),
                       "approved": d.approved, "weight": d.weight, "reason": d.reason, "order": None}
                if d.approved and (self.auto_trade or force_order):
                    block = self._order_block(manual=force_order)
                    if block:
                        rec["order"] = {"skipped": f"shadow: {block}"}
                        await self._shadow_note(block)
                    else:
                        rec["order"] = await self._place(code, q, d.weight)
                await self.hub.emit("decision", rec)
            except Exception as e:
                await self.log(f"{code} 평가 실패: {e}", "error")

    def _order_block(self, manual=False):
        """주문 허용 조건. 반환: 차단 사유 또는 None (Laya 결정은 실행 권한이 아님)"""
        now = dt.datetime.now()
        if now.weekday() >= 5:
            return "주말"
        h0, h1 = self.cfg["engine"].get("trade_hours", ["09:00", "15:20"])
        hm = now.strftime("%H:%M")
        if not (h0 <= hm < h1):
            return f"장 시간 아님({hm}, 허용 {h0}~{h1})"
        if not manual and getattr(self.gate, "model", "") != "trade":
            return "자체 체크포인트(models/laya-trade) 미로드 - 기본 모델은 평가·기록만"
        return None

    async def _shadow_note(self, reason):
        if self._last_err.get("shadow") != reason:
            self._last_err["shadow"] = reason
            await self.log(f"[shadow] 주문 보류: {reason}")

    async def _place(self, code, q, weight):
        if not self.kiwoom:
            raise RuntimeError("키움 미연결")
        eq = self.account["equity"]
        if eq <= 0:
            raise RuntimeError("평가자산 0 - 잔고 조회 상태 확인")
        amt = min(eq * weight, float(self.cfg["risk"]["max_order_amount"]), self.account["orderable"] or eq)
        limit = self.cfg["engine"].get("order_type", "limit") == "limit"
        price = round_tick(q.get("ask") or q["price"]) if limit else None
        qty = int(amt // (price or q.get("ask") or q["price"]))
        if qty <= 0:
            return {"skipped": "주문수량 0"}
        r = await self.kiwoom.order("buy", code, qty, price)
        info = {"mode": config.mode_label(), "side": "buy", "code": code, "qty": qty,
                "price": price or "시장가", "ord_no": r.get("ord_no", ""), "msg": r.get("return_msg", "")}
        await self.hub.emit("order", info)
        return info

    async def manual_order(self, side, code, qty, price):
        if not self.kiwoom:
            raise RuntimeError("키움 미연결")
        price = int(price) if price else None
        r = await self.kiwoom.order(side, norm_code(code), int(qty), price)
        info = {"mode": config.mode_label(), "side": side, "code": norm_code(code), "qty": int(qty),
                "price": price or "시장가", "ord_no": r.get("ord_no", ""), "msg": r.get("return_msg", ""),
                "manual": True}
        await self.hub.emit("order", info)
        return info

    # ---------- 설정 ----------
    async def update_settings(self, patch):
        patch = {k: v for k, v in (patch or {}).items() if k in ("gate", "risk", "engine")}
        saved = deep_merge(self.db.get("settings", {}), patch)
        self.db.set("settings", saved)
        self.cfg = deep_merge(config.load_yaml(), saved)
        await self.log("설정 저장됨")
        return {k: self.cfg[k] for k in ("gate", "risk", "engine")}

    async def set_auto(self, on):
        self.auto_trade = bool(on)
        self.db.set("auto_trade", self.auto_trade)
        await self.log(f"자동매매 {'ON' if on else 'OFF'} ({config.mode_label()})")

    async def switch_mode(self, mock):
        config.set_mode(mock)
        self.auto_trade = False                       # 모드 전환 시 자동매매는 항상 OFF
        self.db.set("auto_trade", False)
        self.account = {"equity": 0, "orderable": 0, "total_pl": 0, "holdings": [], "updated": None}
        await self.start_kiwoom()
        await self.log(f"{config.mode_label()}투자 모드로 전환 (자동매매 OFF)")
        await self.hub.emit("snapshot", self.snapshot(), store=False)
