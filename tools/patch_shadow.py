import sys
p = r"laya_trader\engine.py"
raw = open(p, encoding="utf-8-sig", newline="").read()
crlf = "\r\n" in raw
t = raw.replace("\r\n", "\n")

a1 = ('                if d.approved and (self.auto_trade or force_order):\n'
      '                    rec["order"] = await self._place(code, q, d.weight)\n')
n1 = ('                if d.approved and (self.auto_trade or force_order):\n'
      '                    block = self._order_block(manual=force_order)\n'
      '                    if block:\n'
      '                        rec["order"] = {"skipped": f"shadow: {block}"}\n'
      '                        await self._shadow_note(block)\n'
      '                    else:\n'
      '                        rec["order"] = await self._place(code, q, d.weight)\n')
a2 = '    async def _place(self, code, q, weight):\n'
n2 = '''    def _order_block(self, manual=False):
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

''' + a2
if t.count(a1) != 1 or t.count(a2) != 1:
    print("anchor not found - 중단"); sys.exit(1)
t = t.replace(a1, n1).replace(a2, n2)
if crlf:
    t = t.replace("\n", "\r\n")
open(p, "w", encoding="utf-8", newline="").write(t)
print("patched")
