"""Session 元數據儲存：backend/data/sessions.json。

一個 session = 一個招標專案（命名用招標標題）。chat 嘅 thread_id 就係 session_id。
"""
from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

from . import config
from .services.conneciz import now_iso

SESSIONS_FILE = config.DATA_DIR / "sessions.json"


def _load() -> dict:
    if SESSIONS_FILE.exists():
        try:
            return json.loads(SESSIONS_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _save(data: dict) -> None:
    SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = SESSIONS_FILE.with_name(SESSIONS_FILE.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, SESSIONS_FILE)


def _wrap(sid: str, meta: dict) -> dict:
    return {"id": sid, **meta}


def create_session(title: str = "新專案") -> dict:
    sid = uuid.uuid4().hex
    ts = now_iso()
    data = _load()
    data[sid] = {"title": title, "tender_id": "", "created_at": ts, "updated_at": ts}
    _save(data)
    return _wrap(sid, data[sid])


def list_sessions() -> list[dict]:
    data = _load()
    items = [_wrap(sid, meta) for sid, meta in data.items()]
    items.sort(key=lambda s: s.get("updated_at", ""), reverse=True)
    return items


def get_session(session_id: str) -> dict | None:
    meta = _load().get(session_id)
    return _wrap(session_id, meta) if meta is not None else None


def rename_session(session_id: str, title: str) -> dict | None:
    data = _load()
    meta = data.get(session_id)
    if meta is None:
        return None
    meta["title"] = title
    meta["updated_at"] = now_iso()
    _save(data)
    return _wrap(session_id, meta)


def bind_tender(session_id: str, tender_id: str, title: str = "") -> dict | None:
    data = _load()
    meta = data.get(session_id)
    if meta is None:
        return None
    meta["tender_id"] = tender_id
    if title:
        meta["title"] = title
    meta["updated_at"] = now_iso()
    _save(data)
    return _wrap(session_id, meta)


def touch_session(session_id: str) -> None:
    data = _load()
    meta = data.get(session_id)
    if meta is not None:
        meta["updated_at"] = now_iso()
        _save(data)


def delete_session(session_id: str) -> bool:
    data = _load()
    if session_id in data:
        del data[session_id]
        _save(data)
        return True
    return False
