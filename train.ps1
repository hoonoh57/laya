cd E:\2026\laya
.\.venv\Scripts\python.exe training\build_dataset.py
# 1) 형식 검증: 학습 없이 항목 수와 건너뛴 항목 수만 출력
.\.venv\Scripts\laya-train.exe --data data\dataset\train.jsonl --out models\laya-trade --dry-run
# 2) 실제 학습
.\.venv\Scripts\laya-train.exe --data data\dataset\train.jsonl --out models\laya-trade
# 옵션 확인 (기반 체크포인트, 검증셋 지정 등)
.\.venv\Scripts\laya-train.exe --help
