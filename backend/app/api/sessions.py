"""Session endpoints：列出／建立／改名／綁定招標 + 讀取歷史。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .. import sessions, store
from ..agent.agent import get_agent
from ..schemas import SessionCreate, SessionUpdate
from ..services.common import format_tool_label, parse_markdown_result

router = APIRouter()


@router.get("/sessions")
def list_sessions():
    return {"sessions": sessions.list_sessions()}


@router.post("/sessions")
def create_session(payload: SessionCreate):
    return sessions.create_session(payload.title)


@router.patch("/sessions/{session_id}")
def update_session(session_id: str, payload: SessionUpdate):
    if payload.tender_id is not None:
        tender = store.get_tender(payload.tender_id)
        title = payload.title or (
            (tender.get("title_en") or tender.get("title_zh") or "") if tender else ""
        )
        s = sessions.bind_tender(session_id, payload.tender_id, title)
    elif payload.title is not None:
        s = sessions.rename_session(session_id, payload.title)
    else:
        s = sessions.get_session(session_id)
    if s is None:
        raise HTTPException(status_code=404, detail="session 不存在")
    return s


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str):
    if not sessions.delete_session(session_id):
        raise HTTPException(status_code=404, detail="session 不存在")
    return {"ok": True}


def _extract_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                t = block.get("text")
                if isinstance(t, str):
                    parts.append(t)
                elif isinstance(t, list):
                    for sub in t:
                        if isinstance(sub, str):
                            parts.append(sub)
        return "".join(parts)
    return str(content or "")


def _reconstruct(messages) -> list[dict]:
    """將 LangGraph messages 重建為 frontend 嘅 {role, items[]} 形狀。"""
    out: list[dict] = []
    for m in messages:
        cls = type(m).__name__
        if cls == "HumanMessage":
            out.append({"role": "user", "items": [{"type": "text", "text": _extract_text(m.content)}]})
        elif cls == "AIMessage":
            items: list[dict] = []
            text = _extract_text(m.content)
            if text:
                items.append({"type": "text", "text": text})
            for tc in getattr(m, "tool_calls", []) or []:
                item = {"type": "tool", "name": tc.get("name", "tool"), "done": True}
                label = format_tool_label(tc.get("name", ""), tc.get("args") or {})
                if label:
                    item["label"] = label
                items.append(item)
            if not items:
                items.append({"type": "text", "text": ""})
            out.append({"role": "assistant", "items": items})
        elif cls == "ToolMessage":
            # 填返上一個 assistant message 嘅最後一個未填 result 嘅 tool item
            for i in range(len(out) - 1, -1, -1):
                if out[i]["role"] == "assistant":
                    for j in range(len(out[i]["items"]) - 1, -1, -1):
                        item = out[i]["items"][j]
                        if item["type"] == "tool" and "result" not in item:
                            summary, docs = parse_markdown_result(_extract_text(m.content))
                            item["result"] = summary
                            if docs:
                                out[i]["docs"] = docs
                            break
                    break
        # SystemMessage 忽略
    return out


@router.get("/sessions/{session_id}/messages")
async def get_messages(session_id: str):
    """由 checkpointer 重建歷史消息（resume 用）。"""
    agent = get_agent()
    config = {"configurable": {"thread_id": session_id}}
    snapshot = await agent.aget_state(config)
    msgs = (snapshot.values or {}).get("messages", [])
    return {"messages": _reconstruct(msgs)}
