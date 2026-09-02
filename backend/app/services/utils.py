"""狀態工具：列出已見招標（legacy，沿用舊 pipeline 結構）。"""
from __future__ import annotations

from .conneciz import DEFAULT_STATUS, now_iso


def list_state(state: dict) -> dict:
    """唯讀 snapshot：已見招標列表（最新在前）+ 狀態摘要。"""
    entries = [
        {
            "_id": rid,
            "first_seen": entry.get("first_seen", ""),
            "url": entry.get("url", ""),
            "title_en": entry.get("title_en", ""),
            "title_zh": entry.get("title_zh", ""),
            "tender_ref": entry.get("tender_ref", ""),
            "category": entry.get("category", ""),
            "deadline": entry.get("deadline", ""),
            "status": entry.get("status", DEFAULT_STATUS),
            "status_at": entry.get("status_at", ""),
        }
        for rid, entry in state.get("tenders_seen", {}).items()
    ]
    entries.sort(key=lambda e: e.get("first_seen", ""), reverse=True)
    return {
        "mode": "list",
        "at": now_iso(),
        "count": len(entries),
        "watermark_ts": state.get("watermark_ts"),
        "baseline_ts": state.get("baseline_ts"),
        "tenders_seen": entries,
    }
