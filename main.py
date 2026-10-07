import os, yaml, numpy as np, pandas as pd
os.environ.setdefault("USE_TF", "0")
from src.laya_gate import LayaGate
from src.broker import PaperBroker, LiveBroker
from src.pipeline import TradingPipeline

cfg = yaml.safe_load(open("config/settings.yaml", encoding="utf-8"))
broker = PaperBroker() if cfg["mode"] == "paper" else LiveBroker()
pipe = TradingPipeline(cfg, LayaGate(cfg["laya"]), broker)

# 데모용 합성 데이터 (실전에서는 시세 피드로 교체)
n = 120
close = 70000 + np.cumsum(np.random.randn(n) * 300)
df = pd.DataFrame({"open": close, "high": close + 200, "low": close - 200,
                   "close": close, "volume": np.random.randint(1e5, 5e5, n)})
news = ["삼성전자, 3분기 메모리 업황 개선 기대", "외국인 순매수 3일 연속"]
portfolio = {"daily_pnl_pct": 0.0, "open_positions": 1}

print(pipe.on_signal("005930", "long", df, news, "rsi_reversal", portfolio))
