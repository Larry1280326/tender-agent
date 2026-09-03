"""LangChain tools：將現有 pipeline 函數包裝做 chatbot 可呼叫嘅工具。

每個 tool 嘅 docstring 就係俾 LLM 睇嘅描述；型別標註自動變成 JSON schema。
核心邏輯喺 services + nodes，呢度只做薄薄包裝。
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import InjectedToolArg, tool
from langgraph.types import interrupt

from .. import sessions, store
from ..classify import filter_hk
from ..services import common, conneciz, emailer, file_reader, tender_state, utils
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
    try:
        records = conneciz.dedupe(_list_candidates())
    except Exception as e:  # noqa: BLE001
        return f"暫時讀取唔到 Conneciz 招標列表（{e}），請稍後再試。"
    print(f"Total records: {len(records)}")
    records = [
        r for r in records
        if r.get("_id") not in seen_ids
        and (r.get("issuer_uid") or "", (r.get("deadline") or "")[:10]) not in seen_keys
    ]
    print(f"Filtered records: {len(records)}")
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
    """核實指定招標並生成摘要＋候選（verify → digest → candidates）：先核實官方來源，再由 digest 子代理生成 01_digest.md，最後由 candidates 子代理生成候選產品/供應商 02_candidates.md。"""
    tender = store.get_tender(tender_id)
    if tender is None:
        return f"找不到招標 {tender_id}（可先 select_tender 揀項目，或 list_tenders 查正確 id）。"
    result = get_pipeline().invoke(_build_state(tender_id))
    return common.markdown_result(_format_node_result("核實＋消化＋候選", result), _dossier_docs(tender_id))


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


@tool
def send_email(to: str, subject: str, body: str) -> str:
    """發送電郵。寄出前會先請用戶確認收件人／主旨／內容，用戶批准後先真正寄出。to 可用逗號分隔多個收件人。"""
    decision = interrupt({"type": "send_email_approval", "to": to, "subject": subject, "body": body})
    if not isinstance(decision, dict) or not decision.get("approved"):
        return "用戶已取消，電郵未發送。"
    try:
        return emailer.send_email(to, subject, body)
    except Exception as e:  # noqa: BLE001
        return f"發送失敗：{e}"


@tool
def read_file(path: str) -> str:
    """讀取本地檔案（已上傳／已下載）嘅文字內容。path 係 /upload 回傳嘅路徑（相對 data/ 目錄）或 dossier docs/ 內檔案，支援 pdf/docx/xlsx/doc/xls/txt/csv。當用戶話「上傳咗檔案」並俾咗路徑、或要讀已下載嘅文件時用。"""
    p = Path(path)
    if not p.is_absolute():
        p = store.DATA_DIR / p
    p = p.resolve()
    if not p.is_file() or not p.is_relative_to(store.DATA_DIR):
        return f"找不到檔案或路徑越界（只可讀 {store.DATA_DIR} 內嘅檔案）：{path}"
    ext = p.suffix.lower()
    if ext not in file_reader.READABLE_EXTENSIONS:
        supported = " / ".join(sorted(file_reader.READABLE_EXTENSIONS))
        return f"不支援讀取嘅副檔名：{ext or '(無)'}（只支援 {supported}）。"
    try:
        text = file_reader.extract_text(p)
    except ValueError as e:
        return str(e)
    except Exception as e:  # noqa: BLE001
        return f"讀取失敗：{e}"
    if not text.strip():
        return f"檔案 {p.name} 抽取唔到文字。"
    return f"[{p.name}]\n{text}"


DOSSIER_FILES = ("00_source.md", "01_digest.md", "02_candidates.md")
DOSSIER_TITLES = {
    "00_source.md": "官方來源核實",
    "01_digest.md": "項目摘要",
    "02_candidates.md": "候選產品與供應商",
}


def _dossier_docs(tender_id: str) -> list[dict]:
    """讀取 dossier 內三個 markdown 檔（存在且非空者），回傳 [{title, content}]。

    process_tender 完成後／write_dossier_file 更新後都靠佢，等 frontend 一次過顯示
    全部 markdown 檔，而唔係只得單一檔。
    """
    dossier = store.dossier_dir(tender_id)
    docs: list[dict] = []
    for filename, title in DOSSIER_TITLES.items():
        p = dossier / filename
        if p.is_file():
            content = p.read_text(encoding="utf-8").strip()
            if content:
                docs.append({"title": title, "content": content})
    return docs


def _dossier_file(tender_id: str, filename: str) -> tuple[Path | None, str]:
    """解析 dossier 內 markdown 檔路徑；只准讀寫白名單三個檔。"""
    if store.get_tender(tender_id) is None:
        return None, f"找不到招標 {tender_id}（可先 select_tender 揀項目，或 list_tenders 查正確 id）。"
    if filename not in DOSSIER_FILES:
        allowed = " / ".join(DOSSIER_FILES)
        return None, f"只可讀寫 dossier 內 {allowed}（收到 {filename}）。"
    dossier = store.dossier_dir(tender_id).resolve()
    p = (dossier / filename).resolve()
    if not p.is_relative_to(dossier):
        return None, f"路徑越界：{filename}"
    return p, ""


@tool
def read_dossier_file(tender_id: str, filename: str) -> str:
    """讀取該招標 dossier 內嘅 markdown 檔案：01_digest.md（項目摘要）、02_candidates.md（候選產品與供應商）、00_source.md（官方來源核實）。要更新摘要／報告前，先讀返現有內容。"""
    p, err = _dossier_file(tender_id, filename)
    if err:
        return err
    if not p.is_file():
        return f"檔案未存在：{filename}（可能未執行 process_tender）。"
    return f"[{filename}]\n" + p.read_text(encoding="utf-8")


@tool
def write_dossier_file(tender_id: str, filename: str, content: str) -> str:
    """覆寫該招標 dossier 內嘅 markdown 檔案（只限 00_source.md / 01_digest.md / 02_candidates.md），content 係完整新 markdown。用嚟更新項目摘要或候選產品與供應商報告，唔需要重跑 process_tender。"""
    p, err = _dossier_file(tender_id, filename)
    if err:
        return err
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return common.markdown_result(f"已更新 {filename}。", _dossier_docs(tender_id))


ALL_TOOLS = [
    list_tenders,
    select_tender,
    process_tender,
    search_web,
    read_page,
    download_file,
    read_file,
    read_dossier_file,
    write_dossier_file,
    send_email,
]
