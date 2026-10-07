import json, sys, pandas as pd
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.laya_gate import QUESTIONS
from src.state_builder import build_state

df = pd.read_csv("data/journal/trade_journal.csv").sort_values("timestamp")
out = Path("data/dataset"); out.mkdir(parents=True, exist_ok=True)

rows = []
for r in df.itertuples():
    ind = {k: getattr(r, k) for k in
           ["rsi14", "macd_hist", "bb_position", "atr_pct", "volume_ratio", "ma_trend"]}
    state = build_state(r.symbol, r.side, ind, str(r.news).split("|"), r.signal_source)
    expected = {"entry": "A" if r.outcome == "success" else "B"}
    q = {"entry": QUESTIONS["entry"]}
    if isinstance(r.regime, str) and r.regime:
        expected["regime"] = r.regime
        q["regime"] = QUESTIONS["regime"]
    rows.append({"state": state, "questions": q, "expected": expected})

# 시간순 분할: 무작위로 섞으면 미래 정보가 학습에 새어 들어감
n = len(rows); a, b = int(n * 0.7), int(n * 0.85)
for name, part in [("train", rows[:a]), ("val", rows[a:b]), ("test", rows[b:])]:
    with open(out / f"{name}.jsonl", "w", encoding="utf-8") as f:
        for x in part:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")
    print(name, len(part))
