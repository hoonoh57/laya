from dataclasses import dataclass

@dataclass
class OrderDecision:
    approved: bool
    weight: float
    reason: str

def decide_order(g, gate_cfg: dict, risk_cfg: dict, portfolio: dict) -> OrderDecision:
    # 1) 하드 리스크 한도: 모델과 무관하게 우선 적용
    if portfolio["daily_pnl_pct"] <= -risk_cfg["max_daily_loss_pct"]:
        return OrderDecision(False, 0.0, "일일 손실 한도 초과")
    if portfolio["open_positions"] >= risk_cfg["max_open_positions"]:
        return OrderDecision(False, 0.0, "최대 보유 종목 수 초과")

    # 2) Laya 승인 게이트
    if g.entry_confidence < gate_cfg["min_confidence"]:
        return OrderDecision(False, 0.0, f"신뢰도 부족 ({g.entry_confidence:.2f})")
    if g.p_entry < gate_cfg["min_entry_prob"]:
        return OrderDecision(False, 0.0, f"진입 확률 부족 ({g.p_entry:.2f})")

    # 3) 비중 스케일링
    edge = (g.p_entry - 0.5) * 2                     # 0~1
    conv = g.conviction / 2                          # 0~1
    w = risk_cfg["base_weight"] * (0.5 + edge) * (0.5 + 0.5 * conv)
    if g.regime == "volatile":
        w *= 0.5
    if g.p_news_risk > 0.5:
        w *= (1 - g.p_news_risk)
    w = min(w, risk_cfg["max_position_weight"])
    return OrderDecision(w > 0.005, round(w, 4), "승인" if w > 0.005 else "비중 미달")
