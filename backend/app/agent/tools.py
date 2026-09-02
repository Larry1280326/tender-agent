"""LangChain tools：將現有 pipeline 函數包裝做 chatbot 可呼叫嘅工具。

每個 tool 嘅 docstring 就係俾 LLM 睇嘅描述；型別標註自動變成 JSON schema。
核心邏輯喺 services + nodes，呢度只做薄薄包裝。
"""
from __future__ import annotations

from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolArg, tool

from .. import config, nodes, sessions, store
from ..classify import filter_hk
from ..services import conneciz, reader, serper, tender_state


def _build_state(tender_id: str) -> dict:
    tender = store.get_tender(tender_id)
    return {
        "tender_id": tender_id,
        "tender": tender,
        "status": tender.get("status", "discovered"),
        "dossier_dir": str(store.dossier_dir(tender_id)),
        "issuer": tender.get("issuer", ""),
        "tender_no": tender.get("tender_no") or tender.get("tender_ref", ""),
        "deadline": tender.get("deadline", ""),
        "official_url": tender.get("official_url", ""),
        "doc_links": tender.get("doc_links") or [],
        "logs": [],
        "error": "",
    }


def _format_node_result(action: str, update: dict) -> str:
    lines = [f"{action}完成。"]
    for l in update.get("logs") or []:
        lines.append(f"- [{l.get('level')}] {l.get('message')}")
    for k in ("issuer", "tender_no", "deadline", "official_url"):
        if update.get(k):
            lines.append(f"{k}: {update[k]}")
    return "\n".join(lines)


def _fmt_tender(idx: int, t: dict) -> str:
    """一行招標：序號 + 中文名稱（超連結）+ 截止日期 + 招標方 + tender_id。"""
    title = t.get("title_zh") or t.get("title_en") or t.get("_id") or ""
    url = t.get("url") or ""
    deadline = (t.get("deadline") or "")[:10]
    issuer = (t.get("issuer") or "").strip()
    name = f"[{title}]({url})" if url else title
    line = f"{idx}. {name} ｜ 截止 {deadline}"
    if issuer:
        line += f" ｜ 招標方 {issuer}"
    line += f" ｜ id={t.get('_id', '')}"
    return line


@tool
def list_tenders() -> str:
    """即時讀取 Conneciz 香港非政府招標列表（每項含 tender_id），已嚴格過濾非港機構、剔除重複及已選取項目，俾用戶揀項目。當用戶要求「列出招標／找招標／同步」時用。"""
    selected = store.list_tenders()
    seen_ids = {e.get("_id") for e in selected}  # 已選取項目（by id）
    # 同一 issuer+截止日嘅 sibling 記錄都當「已選取」剔除（避免選咗其中一條，另一條仲出現）
    seen_keys = {
        (e.get("issuer_uid") or "", (e.get("deadline") or "")[:10])
        for e in selected if e.get("issuer_uid")
    }
    records = conneciz.dedupe(conneciz.fetch_tenders(max_pages=5))
    print(*records)
    print()
    print()
    records = [
        r for r in records
        if r.get("_id") not in seen_ids
        and (r.get("issuer_uid") or "", (r.get("deadline") or "")[:10]) not in seen_keys
    ]
    print(*records)
    ts = filter_hk(records, target=10)
    if not ts:
        return "無香港非政府招標。"
    lines = [f"共 {len(ts)} 個香港非政府招標："]
    for i, t in enumerate(ts, 1):
        lines.append(_fmt_tender(i, t))
    return "\n".join(lines)


@tool
def select_tender(tender_id: str, config: Annotated[RunnableConfig, InjectedToolArg]) -> str:
    """用戶揀定某個招標項目後綁定（用 list_tenders 回傳嘅 tender_id）：寫入 tender_state.json 並綁定到目前 session。"""
    tender = next((t for t in conneciz.fetch_tenders() if t.get("_id") == tender_id), None)
    if tender is None:
        return f"找不到 id={tender_id} 嘅招標（可用 list_tenders 查正確 id）。"
    thread_id = config.get("configurable", {}).get("thread_id", "")
    store.save_tender(tender_id, tender_state.new_entry(tender, conneciz.now_iso()))
    title = tender.get("title_zh") or tender.get("title_en") or tender_id
    if thread_id:
        sessions.bind_tender(thread_id, tender_id, title)
    return f"已選取：{title}（tender_id={tender_id}）。之後核實／下載／摘要都對住佢。"


@tool
def verify_tender(tender_id: str) -> str:
    """核實指定招標（用 tender_id）：搜尋官方來源、抽取招標方/編號/截止、寫入 00_source.md。"""
    tender = store.get_tender(tender_id)
    if tender is None:
        return f"找不到招標 {tender_id}（可先 select_tender 揀項目，或 list_tenders 查正確 id）。"
    return _format_node_result("核實", nodes.verify_node(_build_state(tender_id)))


@tool
def download_docs(tender_id: str) -> str:
    """下載指定招標嘅文件到 dossiers/<id>/docs/。"""
    tender = store.get_tender(tender_id)
    if tender is None:
        return f"找不到招標 {tender_id}（可先 select_tender 揀項目，或 list_tenders 查正確 id）。"
    return _format_node_result("下載文件", nodes.download_node(_build_state(tender_id)))


@tool
def digest_tender(tender_id: str) -> str:
    """消化指定招標文件，生成 01_digest.md（項目摘要）。"""
    tender = store.get_tender(tender_id)
    if tender is None:
        return f"找不到招標 {tender_id}（可先 select_tender 揀項目，或 list_tenders 查正確 id）。"
    return _format_node_result("消化", nodes.digest_node(_build_state(tender_id)))


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


ALL_TOOLS = [
    list_tenders,
    select_tender,
    verify_tender,
    download_docs,
    digest_tender,
    search_web,
    read_page,
]
