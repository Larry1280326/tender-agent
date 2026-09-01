"""Backend config：讀 backend/.env + 環境變數，暴露 typed settings。"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parent.parent

# 載入 backend/.env（不覆蓋已存在嘅環境變數）
load_dotenv(BACKEND_ROOT / ".env")


def _get(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


DEEPSEEK_API_KEY = _get("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = _get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = _get("DEEPSEEK_MODEL", "deepseek-chat")
SERPER_API_KEY = _get("SERPER_API_KEY")
JINA_API_KEY = _get("JINA_API_KEY")

# 資料夾（web app 專用）：招標狀態、dossiers、session、checkpoint 都放呢度
DATA_DIR = Path(_get("TENDER_DATA_DIR", str(BACKEND_ROOT / "data"))).resolve()
