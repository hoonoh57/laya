import json
from .indicators import compute_indicators
from .state_builder import build_state
from .sizing import decide_order

class TradingPipeline:
    def __init__(self, cfg, gate, broker):
        self.cfg, self.gate, self.broker = cfg, gate, broker

    def on_signal(self, symbol, side, ohlcv, news, source, portfolio):
        ind = compute_indicators(ohlcv)
        state = build_state(symbol, side, ind, news, source)
        g = self.gate.evaluate(state)
        d = decide_order(g, self.cfg["gate"], self.cfg["risk"], portfolio)

        print(json.dumps({"symbol": symbol, "p_entry": round(g.p_entry, 3),
                          "conf": round(g.entry_confidence, 3), "regime": g.regime,
                          "news_risk": round(g.p_news_risk, 3),
                          "decision": d.reason, "weight": d.weight}, ensure_ascii=False))
        if not d.approved:
            return None
        price = float(ohlcv["close"].iloc[-1])
        qty = int(self.broker.get_equity() * d.weight // price)
        return self.broker.submit_order(symbol, "buy" if side == "long" else "sell", qty, price) if qty > 0 else None
