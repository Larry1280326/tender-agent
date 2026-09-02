"""Chatbot agent：LangGraph create_react_agent（DeepSeek + tools + durable 記憶）。"""
from __future__ import annotations

import aiosqlite
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.prebuilt import create_react_agent

from .. import config
from ..llm import build_model
from .tools import ALL_TOOLS

SYSTEM_PROMPT = (
    "你是「香港招標助理」助手，用正體中文（可夾雜粵語）回覆。\n"
    "你可呼叫工具：list_tenders(page)（即時讀 Conneciz 香港非政府招標列表，每頁 10 個，含 tender_id）、"
    "select_tender（用戶揀定項目後綁定到目前 session）、"
    "process_tender（核實招標並生成摘要，verify → digest）、"
    "search_web（搜尋官方通告）、read_page（讀網頁）、"
    "download_file(url, tender_id?)（下載單一文件，副檔名限 pdf/doc/docx/xls/xlsx/zip 等；可選 tender_id 存入該招標 dossier）、"
    "read_file(path)（讀取本地已上傳／已下載文件嘅文字，支援 pdf/docx/xlsx/doc/xls/txt/csv）。\n"
    "當用戶要求「列出招標」時，call list_tenders。\n"
    "當用戶要求「下載文件／附件」時，call download_file(url)；若係某招標嘅文件，俾埋 tender_id 存入其 dossier。\n"
    "當用戶話「上傳咗檔案」並俾咗路徑（或要讀已下載嘅文件）時，先 call read_file(path) 讀內容再回覆。\n"
    "list_tenders 每頁 10 個；用戶想睇更多／唔鍾意而家呢頁，就 call list_tenders(page=上一頁+1)（例：page=2、3…）。\n"
    "用戶揀項目（例如「選第2個」）時，先用 list_tenders 對應返 tender_id，再 call select_tender(tender_id) 綁定。\n"
    "列出招標時以Markdown表格形式，每項只用「序號. 名稱（超連結） ｜ 截止 日期 ｜ 招標方」欄位。\n"
    "操作招標時用 tender_id；若用戶冇俾 id，先 list_tenders 確認。核實／摘要都 call process_tender(tender_id) 一次過做。\n"
    "回覆要簡潔、條列式，並註明用咗邊啲工具同結果來源。\n"
)

_agent = None
_conn = None


async def init_agent() -> None:
    """建立 agent + durable SqliteSaver（app lifespan 呼叫一次）。"""
    global _agent, _conn
    if _agent is not None:
        return
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    _conn = await aiosqlite.connect(str(config.DATA_DIR / "checkpoints.sqlite"))
    saver = AsyncSqliteSaver(_conn)
    await saver.setup()
    _agent = create_react_agent(build_model(), ALL_TOOLS, prompt=SYSTEM_PROMPT, checkpointer=saver)


async def shutdown_agent() -> None:
    global _conn
    if _conn is not None:
        await _conn.close()
        _conn = None


def get_agent():
    if _agent is None:
        raise RuntimeError("agent 未初始化（app lifespan 應已呼叫 init_agent）")
    return _agent
