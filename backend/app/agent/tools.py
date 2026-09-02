"""LangChain tools：將現有 pipeline 函數包裝做 chatbot 可呼叫嘅工具。

每個 tool 嘅 docstring 就係俾 LLM 睇嘅描述；型別標註自動變成 JSON schema。
核心邏輯喺 services + nodes，呢度只做薄薄包裝。
"""
from __future__ import annotations

from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolArg, tool

from .. import sessions, store
from ..classify import filter_hk
from ..services import common, conneciz, tender_state, utils
from .pipeline import get_pipeline
from .web_tools import read_page, search_web


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


# list_tenders 嘅讀取範圍（2 天至 2 個月，最多 5 頁）。select_tender 必須用同一範圍／cache key
# 先保證「列出嚟嘅 tender_id」一定搵得返 —— 用唔同範圍會令 select 搵唔到 list 顯示嘅項目。
LIST_MAX_PAGES = 5
LIST_MIN_DAYS_AHEAD = 2
LIST_MAX_DAYS_AHEAD = 60


def _list_candidates() -> list[dict]:
    """list_tenders / select_tender 共用嘅候選集：同一 fetch 範圍（同一個 TTL cache key）。"""
    return conneciz.fetch_tenders(
        max_pages=LIST_MAX_PAGES,
        min_days_ahead=LIST_MIN_DAYS_AHEAD,
        max_days_ahead=LIST_MAX_DAYS_AHEAD,
    )


def _find_tender(tender_id: str) -> dict | None:
    """按 id 搵招標：先喺 list_tenders 顯示嗰個範圍搵，搵唔到先掃闊啲（預設 3 頁 × 365 日）兜底。"""
    for rec in _list_candidates():
        if rec.get("_id") == tender_id:
            return rec
    for rec in conneciz.fetch_tenders():  # 預設範圍兜底（例如舊日見到嘅項目）
        if rec.get("_id") == tender_id:
            return rec
    return None


@tool
def list_tenders(page: int = 1) -> str:
    """即時讀取 Conneciz 香港非政府招標列表（每項含 tender_id），已嚴格過濾非港機構、剔除重複及已選取項目。分頁：每頁 10 個，page=1 第一頁；用戶想睇更多／唔鍾意而家呢頁就 call 下一頁（page=2、3…）。當用戶要求「列出招標／找招標／同步」時用。"""
    page = max(1, page)
    selected = store.list_tenders()
    seen_ids = {e.get("_id") for e in selected}  # 已選取項目（by id）
    # 同一 issuer+截止日嘅 sibling 記錄都當「已選取」剔除（避免選咗其中一條，另一條仲出現）
    seen_keys = {
        (e.get("issuer_uid") or "", (e.get("deadline") or "")[:10])
        for e in selected if e.get("issuer_uid")
    }
    records = conneciz.dedupe(_list_candidates())
    print(*records)
    print()
    print()
    records = [
        r for r in records
        if r.get("_id") not in seen_ids
        and (r.get("issuer_uid") or "", (r.get("deadline") or "")[:10]) not in seen_keys
    ]
    print(*records)
    ts = filter_hk(records, target=10, offset=(page - 1) * 10)
    if not ts:
        return "無香港非政府招標。" if page == 1 else f"第 {page} 頁冇更多香港非政府招標。"
    lines = [f"第 {page} 頁，共 {len(ts)} 個香港非政府招標："]
    for i, t in enumerate(ts, 1):
        lines.append(_fmt_tender(i, t))
    return "\n".join(lines)


@tool
def select_tender(tender_id: str, config: Annotated[RunnableConfig, InjectedToolArg]) -> str:
    """用戶揀定某個招標項目後綁定（用 list_tenders 回傳嘅 tender_id）：寫入 tender_state.json 並綁定到目前 session。"""
    tender = _find_tender(tender_id)
    if tender is None:
        return f"找不到 id={tender_id} 嘅招標（可用 list_tenders 查正確 id）。"
    thread_id = config.get("configurable", {}).get("thread_id", "")
    store.save_tender(tender_id, tender_state.new_entry(tender, conneciz.now_iso()))
    title = tender.get("title_zh") or tender.get("title_en") or tender_id
    if thread_id:
        sessions.bind_tender(thread_id, tender_id, title)
    return f"已選取：{title}（tender_id={tender_id}）。之後核實／摘要都對住佢。"


@tool
def process_tender(tender_id: str) -> str:
    """核實指定招標並生成摘要（verify → digest）：先核實官方來源，再由 digest 子代理（可搜尋/讀頁）生成 01_digest.md。"""
    tender = store.get_tender(tender_id)
    if tender is None:
        return f"找不到招標 {tender_id}（可先 select_tender 揀項目，或 list_tenders 查正確 id）。"
    result = get_pipeline().invoke(_build_state(tender_id))
    return common.markdown_result(_format_node_result("核實＋消化", result), result.get("digest_md"))


@tool
def download_file(url: str, tender_id: str = "") -> str:
    """下載單一文件（URL 副檔名須為 pdf/doc/docx/xls/xlsx/zip/txt/csv/ppt/pptx/rar/7z）。有 tender_id 就存入該招標 dossier 嘅 docs/，否則存到 data/downloads/。回傳本地路徑同檔案大小。"""
    if not (url.startswith("http://") or url.startswith("https://")):
        return "URL 唔係 http(s) 連結。"
    ext = utils.allowed_ext(url)
    if ext is None:
        allowed = " / ".join(sorted(utils.ALLOWED_EXTENSIONS))
        return f"不支援嘅副檔名：{url}（只支援 {allowed}）。"
    if tender_id:
        if store.get_tender(tender_id) is None:
            return f"找不到招標 {tender_id}（可用 list_tenders 查正確 id）。"
        dest = store.dossier_dir(tender_id) / "docs"
    else:
        dest = store.DATA_DIR / "downloads"
    dest.mkdir(parents=True, exist_ok=True)
    result = utils.download(url, dest, 1, 100 * 1024 * 1024)
    if not result.get("ok"):
        return f"下載失敗：{result.get('error') or url}"
    path = dest / result["file"]
    return common.markdown_result(
        f"已下載 {result['file']}（{result['size']} bytes, sha1 {result['sha1']}）→ {path}",
        None,
    )


ALL_TOOLS = [
    list_tenders,
    select_tender,
    process_tender,
    search_web,
    read_page,
    download_file,
]
