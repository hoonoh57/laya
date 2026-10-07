import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
(ROOT / "logs").mkdir(exist_ok=True)
# pythonw.exe는 콘솔이 없어 stdout이 None이다 → uvicorn 오류 방지
if sys.stdout is None:
    sys.stdout = open(ROOT / "logs" / "stdout.log", "a", encoding="utf-8", buffering=1)
if sys.stderr is None:
    sys.stderr = sys.stdout

from laya_trader.server import run  # noqa: E402

run()
