"""Chatbot endpoint：SSE 串流 agent 回覆 + 工具呼叫事件 + 人類核准（send_email）。"""
from __future__ import annotations

import json
from typing import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from langgraph.types import Command

from .. import sessions
from ..agent.agent import get_agent
from ..schemas import ApproveRequest, ChatRequest
from ..services.common import parse_markdown_result

router = APIRouter()


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


async def _sse_stream(agent, astream_input, config) -> AsyncIterator[str]:
    """將 agent.astream_events 轉做 SSE。共用於首次對話同核准後 resume。"""
    tool_depth = 0
    try:
        async for event in agent.astream_events(
            astream_input,
            config=config,
            version="v2",
        ):
            kind = event["event"]
            if kind == "on_tool_start":
                tool_depth += 1
                name = event.get("name") or ""
                yield _sse({"event": "tool_start", "node": name, "message": f"使用工具 {name}"})
            elif kind == "on_tool_end":
                name = event.get("name") or ""
                out = event["data"].get("output")
                content = getattr(out, "content", out)
                if not isinstance(content, str):
                    content = str(out)
                summary, docs = parse_markdown_result(content)
                yield _sse({"event": "tool_end", "node": name, "message": summary, "docs": docs})
                tool_depth -= 1
            elif kind == "on_chat_model_stream":
                if tool_depth > 0:
                    continue  # 工具內部嘅 LLM 呼叫，唔當用戶睇嘅文字
                content = getattr(event["data"].get("chunk"), "content", None)
                if isinstance(content, str) and content:
                    yield _sse({"event": "text", "delta": content})
            elif kind == "on_chain_stream":
                chunk = event["data"].get("chunk")
                if isinstance(chunk, dict) and "__interrupt__" in chunk:
                    inter = chunk["__interrupt__"][0]
                    yield _sse({
                        "event": "approval_required",
                        "interrupt_id": getattr(inter, "id", ""),
                        "payload": getattr(inter, "value", inter),
                    })
        yield _sse({"event": "done", "message": ""})
    except Exception as e:  # noqa: BLE001
        yield _sse({"event": "error", "message": f"{type(e).__name__}: {e}"})


@router.post("/chat/stream")
async def chat_stream(payload: ChatRequest):
    if not payload.message.strip():
        return StreamingResponse(
            iter([_sse({"event": "error", "message": "訊息為空"})]),
            media_type="text/event-stream",
        )

    async def gen():
        agent = get_agent()
        config = {"configurable": {"thread_id": payload.thread_id}}

        messages: list = []
        sess = sessions.get_session(payload.thread_id)
        if sess and sess.get("tender_id"):
            messages.append((
                "system",
                f"目前專案：{sess['title']}（tender_id={sess['tender_id']}）。"
                "當用戶講「呢個／此項目／它／這個項目」時，用呢個 tender_id 操作。",
            ))
        messages.append(("user", payload.message))
        sessions.touch_session(payload.thread_id)

        async for sse in _sse_stream(agent, {"messages": messages}, config):
            yield sse

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/chat/approve")
async def chat_approve(payload: ApproveRequest):
    """核准／取消 send_email：以 Command(resume=...) 繼續同一個 thread 嘅中斷。"""
    agent = get_agent()
    config = {"configurable": {"thread_id": payload.thread_id}}

    async def gen():
        # 冇中斷就唔好盲目 resume（會開新一輪）。
        snapshot = await agent.aget_state(config)
        if not snapshot.next:
            yield _sse({"event": "error", "message": "冇待處理嘅核准（可能已過期）。"})
            return
        async for sse in _sse_stream(
            agent,
            Command(resume={"approved": payload.approved}),
            config,
        ):
            yield sse

    return StreamingResponse(gen(), media_type="text/event-stream")
