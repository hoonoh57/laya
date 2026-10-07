import sys
p = r"laya_trader\engine.py"
raw = open(p, encoding="utf-8-sig", newline="").read()
crlf = "\r\n" in raw
t = raw.replace("\r\n", "\n")

a1 = "        self._bal_lock = asyncio.Lock()\n"
n1 = a1 + "        self._bal_next = 0.0\n        self._bal_pending = False\n        self._bal_err_at = -1e9\n"
s2, e2 = "    async def refresh_balance_safe(self):", "    def portfolio(self):"
if t.count(a1) != 1 or t.count(s2) != 1 or t.count(e2) != 1:
    print("anchor not found - 중단"); sys.exit(1)
new2 = '''    async def refresh_balance_safe(self, force=False):
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

'''
t = t.replace(a1, n1)
i, j = t.index(s2), t.index(e2)
t = t[:i] + new2 + t[j:]
if crlf:
    t = t.replace("\n", "\r\n")
open(p, "w", encoding="utf-8", newline="").write(t)
print("patched")
