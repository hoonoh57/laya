from dataclasses import dataclass
from pathlib import Path

# 학습 데이터의 질문 스키마와 '정확히' 같아야 함 (키·문구·옵션 모두)
QUESTIONS = {
    "entry": {
        "type": "choice",
        "instructions": "Given the indicator state and news, should this trade signal be executed now?",
        "criteria": {
            "A": "yes, execute: indicators and news support the signal direction",
            "B": "no, skip: conflicting, weak, or risky setup",
        },
    },
    "regime": {
        "type": "choice",
        "instructions": "What is the current market regime for this symbol?",
        "criteria": {
            "trend": "clear directional trend",
            "range": "sideways, mean-reverting",
            "volatile": "unstable, large swings, event-driven",
        },
    },
    "news_risk": {
        "type": "choice",
        "instructions": "Does the news contain event risk against the signal direction?",
        "criteria": {"A": "yes, adverse news or event risk", "B": "no adverse news"},
    },
    "conviction": {
        "type": "score",
        "instructions": "How strong is this setup overall?",
        "criteria": ["weak", "moderate", "strong"],
    },
}


@dataclass
class GateResult:
    p_entry: float
    entry_confidence: float
    regime: str
    p_news_risk: float
    conviction: float          # 0.0 ~ 2.0 (기대값)
    raw: dict


def _option_prob(ans: dict, key: str) -> float:
    """버전별 응답 필드 차이에 대비한 방어적 추출."""
    for field in ("probabilities", "distribution", "probs"):
        d = ans.get(field)
        if isinstance(d, dict) and key in d:
            return float(d[key])
    conf = float(ans.get("answer_confidence", ans.get("confidence", 0.5)))
    return conf if ans.get("choice") == key else 1 - conf


class LayaGate:
    def __init__(self, cfg: dict):
        from laya import Router
        self.max_len = cfg.get("max_len", 1024)
        self.router = Router(device=cfg.get("device", "cpu"))
        self.model = cfg.get("model", "multilingual")
        ft_dir = Path(cfg.get("finetuned_dir", ""))
        if ft_dir.exists() and any(ft_dir.iterdir()):
            self.router.register("trade", str(ft_dir))   # 로컬 파인튜닝 체크포인트
            self.model = "trade"

    def evaluate(self, state: dict) -> GateResult:
        res = self.router.predict(state, QUESTIONS, model=self.model, max_len=self.max_len)
        a = res["answers"]
        e = a["entry"]
        return GateResult(
            p_entry=_option_prob(e, "A"),
            entry_confidence=float(e.get("answer_confidence", e.get("confidence", 0.0))),
            regime=a["regime"]["choice"],
            p_news_risk=_option_prob(a["news_risk"], "A"),
            conviction=float(a["conviction"]["score"]),
            raw=res,
        )
