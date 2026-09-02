"""Chatbot endpoint：SSE 串流 agent 回覆 + 工具呼叫事件。"""
from __future__ import annotations

import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from .. import sessions
from ..agent.agent import get_agent
from ..schemas import ChatRequest
from ..services.common import parse_markdown_result

router = APIRouter()


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/chat/stream")
async def chat_stream(payload: ChatRequest):
    if not payload.message.strip():
        return StreamingResponse(
            iter([_sse({"event": "error", "message": "訊息為空"})]),
            media_type="text/event-stream",
        )

    async def gen():
        try:
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

            tool_depth = 0
            async for event in agent.astream_events(
                {"messages": messages},
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
                    summary, markdown = parse_markdown_result(content)
                    yield _sse({"event": "tool_end", "node": name, "message": summary, "markdown": markdown})
                    tool_depth -= 1
                elif kind == "on_chat_model_stream":
                    if tool_depth > 0:
                        continue  # 工具內部嘅 LLM 呼叫，唔當用戶睇嘅文字
                    content = getattr(event["data"].get("chunk"), "content", None)
                    if isinstance(content, str) and content:
                        yield _sse({"event": "text", "delta": content})
            yield _sse({"event": "done", "message": ""})
        except Exception as e:  # noqa: BLE001
            yield _sse({"event": "error", "message": f"{type(e).__name__}: {e}"})

    return StreamingResponse(gen(), media_type="text/event-stream")
