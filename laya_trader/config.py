import os
from pathlib import Path

import yaml
from dotenv import load_dotenv, set_key

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"


def load_env():
    load_dotenv(ENV_PATH, override=True)


def env(key, default=""):
    return (os.getenv(key) or default).strip()


def is_mock() -> bool:
    return env("TRADING_MOCK", "true").lower() in ("1", "true", "yes", "y")


def mode_label() -> str:
    return "모의" if is_mock() else "실전"


def kiwoom_creds() -> dict:
    p = "KIWOOM_MOCK_" if is_mock() else "KIWOOM_REAL_"
    return {"appkey": env(p + "APPKEY"), "secretkey": env(p + "SECRETKEY"),
            "account": env(p + "ACCOUNT"), "mock": is_mock()}


def set_mode(mock: bool):
    set_key(str(ENV_PATH), "TRADING_MOCK", "true" if mock else "false", quote_mode="never")
    load_env()


def load_yaml() -> dict:
    return yaml.safe_load((ROOT / "config" / "settings.yaml").read_text(encoding="utf-8"))


load_env()
