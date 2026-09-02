"""網頁工具：search_web / read_page。

由 tools.py 抽出做獨立模組，避免 circular import：pipeline.py 嘅 digest 子代理
都要用呢兩個工具，而 tools.py 又要 import pipeline.py（process_tender）。
"""
from __future__ import annotations

from langchain_core.tools import tool

from .. import config
from ..services import reader, serper


@tool
def search_web(query: str) -> str:
    """用 Serper 搜尋官方招標通告（回傳標題＋連結＋摘要）。"""
    if not config.SERPER_API_KEY:
        return "缺 SERPER_API_KEY（放 backend/.env）。"
    try:
        res = serper.search(query, config.SERPER_API_KEY, num=10)
    except Exception as e:  # noqa: BLE001
        return f"搜尋失敗：{e}"
    if not res:
        return "無搜尋結果。"
    return "\n".join(f"- {r['title']} — {r['link']}" for r in res)


@tool
def read_page(url: str) -> str:
    """用 Jina Reader 讀取網頁內容（markdown），可用嚟查官方通告詳情。"""
    if not config.JINA_API_KEY:
        return "缺 JINA_API_KEY（放 backend/.env）。"
    try:
        text = reader.read(url, config.JINA_API_KEY)
    except Exception as e:  # noqa: BLE001
        return f"讀取失敗：{e}"
    return text
