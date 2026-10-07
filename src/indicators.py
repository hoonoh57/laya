import pandas as pd

def compute_indicators(df: pd.DataFrame) -> dict:
    """df: columns = open, high, low, close, volume (시간순)"""
    c = df["close"]
    delta = c.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rsi = 100 - 100 / (1 + gain / loss)

    ema12, ema26 = c.ewm(span=12).mean(), c.ewm(span=26).mean()
    macd = ema12 - ema26
    macd_hist = macd - macd.ewm(span=9).mean()

    ma20, sd20 = c.rolling(20).mean(), c.rolling(20).std()
    bb_pos = (c - (ma20 - 2 * sd20)) / (4 * sd20)          # 0=하단, 1=상단

    tr = pd.concat([df["high"] - df["low"],
                    (df["high"] - c.shift()).abs(),
                    (df["low"] - c.shift()).abs()], axis=1).max(axis=1)
    atr_pct = tr.rolling(14).mean() / c * 100
    vol_ratio = df["volume"] / df["volume"].rolling(20).mean()
    ma60 = c.rolling(60).mean()

    last = -1
    return {
        "rsi14": round(float(rsi.iloc[last]), 1),
        "macd_hist": round(float(macd_hist.iloc[last]), 4),
        "bb_position": round(float(bb_pos.iloc[last]), 2),
        "atr_pct": round(float(atr_pct.iloc[last]), 2),
        "volume_ratio": round(float(vol_ratio.iloc[last]), 2),
        "ma_trend": "up" if ma20.iloc[last] > ma60.iloc[last] else "down",
    }
