"""所選項目狀態：backend/data/tender_state.json。

只存放用戶「選取咗」嘅招標項目（一 project 一 entry），取代舊 pipeline_state.json
（嗰個存晒全部已發現記錄 + watermark）。key = tender_id。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .common import data_root
from .conneciz import DEFAULT_STATUS, now_iso

TENDER_STATE_FILE = data_root() / "tender_state.json"


def load() -> dict:
    if TENDER_STATE_FILE.exists():
        try:
            return json.loads(TENDER_STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save(data: dict) -> None:
    TENDER_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = TENDER_STATE_FILE.with_name(TENDER_STATE_FILE.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, TENDER_STATE_FILE)


def get(tender_id: str) -> dict | None:
    return load().get(tender_id)


def upsert(tender_id: str, entry: dict) -> None:
    data = load()
    data[tender_id] = entry
    save(data)


def update(tender_id: str, patch: dict) -> dict | None:
    """合併 patch 入現有 entry（不存在則略過）。回傳更新後 entry。"""
    data = load()
    entry = data.get(tender_id)
    if entry is None:
        return None
    entry.update(patch)
    save(data)
    return entry


def set_status(tender_id: str, status: str) -> bool:
    data = load()
    entry = data.get(tender_id)
    if entry is None:
        return False
    entry["status"] = status
    entry["status_at"] = now_iso()
    save(data)
    return True


def list_all() -> list[dict]:
    """所選項目列表（最新 first_seen 在前），每項附 _id。"""
    entries = [{"_id": rid, **entry} for rid, entry in load().items()]
    entries.sort(key=lambda e: e.get("first_seen", ""), reverse=True)
    return entries


def new_entry(rec: dict, first_seen: str) -> dict:
    """由 Conneciz slim 記錄建 entry（status = discovered）。"""
    return {
        "first_seen": first_seen,
        "url": rec.get("url", ""),
        "title_en": rec.get("title_en", ""),
        "title_zh": rec.get("title_zh", ""),
        "tender_ref": rec.get("tender_ref", ""),
        "category": rec.get("category", ""),
        "deadline": rec.get("deadline", ""),
        "status": DEFAULT_STATUS,
        "status_at": first_seen,
        "issuer": "",
        "tender_no": "",
        "official_url": "",
        "doc_links": [],
    }
