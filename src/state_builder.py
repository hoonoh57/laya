def build_state(symbol: str, side: str, indicators: dict,
                news: list[str], signal_source: str) -> dict:
    """Laya 컨텍스트가 짧으므로(1024토큰, 질문 포함) state를 압축해서 넣는다."""
    return {
        "symbol": symbol,
        "signal_side": side,                 # long / short
        "signal_source": signal_source,      # 예: "rsi_reversal", "breakout"
        "indicators": indicators,
        "news_headlines": [n[:200] for n in news[:3]],
    }
