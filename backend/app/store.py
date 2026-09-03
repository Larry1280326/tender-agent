"""招標狀態儲存：喺 import services 前先將 TENDER_DATA_DIR 指向 backend/data/。"""
from __future__ import annotations

import os
from pathlib import Path

from . import config

# 關鍵：先指向隔離資料夾，再 import services（佢哋讀 TENDER_DATA_DIR 決定資料位置）。
os.environ["TENDER_DATA_DIR"] = str(config.DATA_DIR)
# 讓 services 同 backend 共用嘅 API key 讀到（services 用 shell env 優先）
os.environ.setdefault("SERPER_API_KEY", config.SERPER_API_KEY)
os.environ.setdefault("JINA_API_KEY", config.JINA_API_KEY)

from .services import tender_state  # noqa: E402

DATA_DIR = config.DATA_DIR
DATA_DIR.mkdir(parents=True, exist_ok=True)
DOSSIERS_DIR = DATA_DIR / "dossiers"


# ── tender_state.json（所選項目） ─────────────────────────────────────────────

def list_tenders() -> list[dict]:
    return tender_state.list_all()


def get_tender(tender_id: str) -> dict | None:
    entry = tender_state.get(tender_id)
    if entry is None:
        return None
    return {"_id": tender_id, **entry}


def save_tender(tender_id: str, entry: dict) -> None:
    tender_state.upsert(tender_id, entry)


def update_tender(tender_id: str, patch: dict) -> dict | None:
    return tender_state.update(tender_id, patch)


def delete_tender(tender_id: str) -> bool:
    return tender_state.delete(tender_id)


def set_tender_status(tender_id: str, status: str) -> bool:
    return tender_state.set_status(tender_id, status)


def dossier_dir(tender_id: str) -> Path:
    return DOSSIERS_DIR / tender_id
