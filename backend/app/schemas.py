"""Pydantic models：API 請求／回應 + 串流事件。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class Tender(BaseModel):
    _id: str = ""
    tender_ref: str = ""
    title_en: str = ""
    title_zh: str = ""
    category: str = ""
    deadline: str = ""
    url: str = ""
    first_seen: str = ""
    status: str = "discovered"
    status_at: str = ""


class ChatRequest(BaseModel):
    thread_id: str = "default"
    message: str = ""


class UploadResponse(BaseModel):
    path: str
    filename: str
    size: int


class SessionCreate(BaseModel):
    title: str = "新專案"


class SessionUpdate(BaseModel):
    title: str | None = None
    tender_id: str | None = None


class Session(BaseModel):
    id: str
    title: str = "新專案"
    tender_id: str = ""
    created_at: str = ""
    updated_at: str = ""
