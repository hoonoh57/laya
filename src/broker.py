import csv, datetime as dt
from abc import ABC, abstractmethod
from pathlib import Path

class Broker(ABC):
    @abstractmethod
    def get_equity(self) -> float: ...
    @abstractmethod
    def submit_order(self, symbol: str, side: str, qty: int, price: float) -> dict: ...

class PaperBroker(Broker):
    def __init__(self, equity: float = 100_000_000, log="data/paper_orders.csv"):
        self.equity, self.log = equity, Path(log)
        self.log.parent.mkdir(parents=True, exist_ok=True)

    def get_equity(self): return self.equity

    def submit_order(self, symbol, side, qty, price):
        row = [dt.datetime.now().isoformat(), symbol, side, qty, price]
        with self.log.open("a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(row)
        return {"status": "filled(paper)", "symbol": symbol, "qty": qty}

class LiveBroker(Broker):
    """실제 증권사 API(예: 한국투자증권 KIS, 키움, IBKR)를 연결하는 자리.
    인증·호가 단위·주문 오류 처리·재시도·멱등키를 반드시 구현할 것."""
    def get_equity(self): raise NotImplementedError
    def submit_order(self, *a, **k): raise NotImplementedError
