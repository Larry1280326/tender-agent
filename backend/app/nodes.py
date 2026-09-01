"""Per-tender 節點邏輯：verify → download → digest。

沿用 services 做所有 fetching（reader/serper/utils/conneciz）；LLM 只做判斷同生成。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import config
from .services import reader, serper, utils
from .store import set_tender_status, update_tender

# 佔位/junk 標題清單（數據品質過濾）
JUNK_TITLES = [
    "unknown subject", "暫時沒有相關資料"
]


def _log(node: str, message: str, level: str = "info") -> dict:
    return {"node": node, "level": level, "message": message}


def _is_junk(tender: dict) -> bool:
    te = (tender.get("title_en") or "").strip().lower()
    tz = (tender.get("title_zh") or "").strip().lower()
    if not te and not tz:
        return True
    if not tender.get("url"):
        return True
    for j in JUNK_TITLES:
        if j in te or j in tz:
            return True
    return False


def _pick_official(candidates: list[dict], issuer: str) -> dict | None:
    """由 Serper 結果揀最似官方嘅連結（gov.hk/edu.hk 優先，conneciz 排除）。"""

    def score(r: dict) -> int:
        link = (r.get("link") or "").lower()
        s = 0
        if ".gov.hk" in link:
            s += 100
        elif ".edu.hk" in link:
            s += 60
        elif ".gov." in link:
            s += 50
        if "conneciz" in link:
            s -= 1000
        return s

    if not candidates:
        return None
    best = max(candidates, key=score)
    return best if score(best) > 0 else None


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _llm_judge(tender: dict, extracted: dict, official_url: str, official_text: str) -> dict:
    """LLM 判斷地區/官方欄位；失敗時回退 regex 抽取結果。"""
    try:
        from .llm import build_model
        model = build_model()
        prompt = (
            "你是香港公開招標項目分析助手。根據下方資料，判斷並輸出 JSON（只輸出 JSON，勿加 markdown 程式碼框）。\n"
            "JSON 鍵：region（如 HK/其他）、issuer（招標方）、tender_no（招標號碼）、deadline（截止日期）、"
            "doc_links（文件下載連結陣列）、notes（一句話備註，可含時區/資料差異）。\n"
            f"Conneciz 原始資料：{json.dumps(tender, ensure_ascii=False)}\n"
            f"Conneciz 詳情頁抽取：{json.dumps(extracted, ensure_ascii=False)}\n"
            f"官方頁 URL：{official_url or '(無)'}\n"
            f"官方頁內容（截斷）：{(official_text or '')[:6000]}\n"
        )
        resp = model.invoke([("system", "你是香港招標分析助手，只輸出 JSON。"), ("human", prompt)])
        content = resp.content if isinstance(resp.content, str) else str(resp.content)
        return json.loads(_strip_code_fences(content))
    except Exception as e:  # noqa: BLE001
        return {"region": "", "notes": f"LLM 判斷失敗（回退 regex）：{e}"}


def _write_source(dossier: Path, tender: dict, extracted: dict, official: dict | None,
                  official_url: str, judgement: dict) -> None:
    lines = [
        "# 官方來源核實筆記",
        "",
        f"- 招標編號：{judgement.get('tender_no') or tender.get('tender_ref') or ''}",
        f"- 招標方：{judgement.get('issuer') or extracted.get('issuer') or ''}",
        f"- 截止日期：{judgement.get('deadline') or tender.get('deadline') or ''}",
        f"- 地區：{judgement.get('region') or '未判定'}",
        f"- 官方來源：{official_url or '(未找到，以 Conneciz 為準)'}",
    ]
    if official:
        lines += ["", "## Serper 候選", f"- {official.get('title')} — {official.get('link')}"]
    if judgement.get("notes"):
        lines += ["", f"備註：{judgement['notes']}"]
    lines += ["", "## Conneciz 原始資料", f"```json", json.dumps(tender, ensure_ascii=False, indent=2), "```"]
    (dossier / "00_source.md").write_text("\n".join(lines), encoding="utf-8")


def verify_node(state: dict) -> dict:
    logs: list[dict] = []
    tender = state["tender"]
    tid = state["tender_id"]
    dossier = Path(state["dossier_dir"])
    dossier.mkdir(parents=True, exist_ok=True)
    logs.append(_log("verify", "開始核實（讀 Conneciz 詳情 → 搜尋官方 → LLM 判斷）"))

    if _is_junk(tender):
        set_tender_status(tid, "searched")
        return {"status": "searched", "logs": [_log("verify", "標題屬佔位/junk，跳過核實", "warn")]}

    ref = tender.get("tender_ref") or ""
    title_en = tender.get("title_en") or ""
    title_zh = tender.get("title_zh") or ""
    url = tender.get("url") or ""

    extracted: dict = {}
    if url and config.JINA_API_KEY:
        try:
            text = reader.read(url, config.JINA_API_KEY)
            extracted = reader.extract(text)
            logs.append(_log("verify", f"Conneciz 詳情頁抽取：{json.dumps(extracted, ensure_ascii=False)}"))
        except Exception as e:  # noqa: BLE001
            logs.append(_log("verify", f"Conneciz 詳情頁讀取失敗：{e}", "warn"))

    issuer = extracted.get("issuer") or ""
    tender_no = extracted.get("tender_no") or ref

    # 搜尋官方來源
    queries = list(dict.fromkeys([q for q in [
        f"{tender_no} {issuer} 招標".strip(),
        f"{tender_no} {title_en}".strip(),
        f"{title_zh} 招標".strip(),
    ] if q.strip()]))
    candidates: list[dict] = []
    if config.SERPER_API_KEY:
        for q in queries:
            try:
                res = serper.search(q, config.SERPER_API_KEY, num=10)
                for r in res:
                    r["_query"] = q
                candidates.extend(res)
                logs.append(_log("verify", f"搜尋「{q}」：{len(res)} 條"))
            except Exception as e:  # noqa: BLE001
                logs.append(_log("verify", f"Serper 搜尋失敗（{q}）：{e}", "error"))
    else:
        logs.append(_log("verify", "缺 SERPER_API_KEY，跳過官方搜尋", "warn"))

    official = _pick_official(candidates, issuer)
    official_url = official.get("link", "") if official else ""
    doc_links = list(extracted.get("doc_links") or [])
    official_text = ""
    if official_url and config.JINA_API_KEY:
        logs.append(_log("verify", f"選定官方頁：{official.get('title')} — {official_url}"))
        try:
            official_text = reader.read(official_url, config.JINA_API_KEY)
            off_ext = reader.extract(official_text)
            doc_links = list(off_ext.get("doc_links") or doc_links)
            tender_no = off_ext.get("tender_no") or tender_no
            issuer = off_ext.get("issuer") or issuer
            extracted.setdefault("deadline", off_ext.get("deadline"))
        except Exception as e:  # noqa: BLE001
            logs.append(_log("verify", f"官方頁讀取失敗：{e}", "warn"))
    else:
        logs.append(_log("verify", "未找到官方來源，以 Conneciz 資料為準", "warn"))

    judgement = _llm_judge(tender, extracted, official_url, official_text)
    _write_source(dossier, tender, extracted, official, official_url, judgement)
    final_deadline = extracted.get("deadline") or tender.get("deadline", "")
    final_doc_links = list(dict.fromkeys(doc_links))
    set_tender_status(tid, "searched")
    # 持久化核實結果，等 download/digest 喺之後嘅 turn 都攞到 doc_links 等欄位
    update_tender(tid, {
        "issuer": issuer,
        "tender_no": tender_no,
        "deadline": final_deadline,
        "official_url": official_url,
        "doc_links": final_doc_links,
    })
    logs.append(_log("verify", f"核實完成：issuer={issuer} tender_no={tender_no}"))

    return {
        "status": "searched",
        "issuer": issuer,
        "tender_no": tender_no,
        "deadline": final_deadline,
        "official_url": official_url,
        "doc_links": final_doc_links,
        "logs": logs,
    }


def download_node(state: dict) -> dict:
    logs: list[dict] = []
    tid = state["tender_id"]
    dossier = Path(state["dossier_dir"])
    links = [l for l in (state.get("doc_links") or []) if isinstance(l, str) and l.startswith("http")]

    if not links:
        set_tender_status(tid, "searched")
        return {"logs": [_log("download", "無直接下載連結（可能需登入／線下索取，留待用戶處理）", "warn")]}

    dest_dir = dossier / "docs"
    dest_dir.mkdir(parents=True, exist_ok=True)
    max_bytes = 100 * 1024 * 1024
    results = [utils.download(u, dest_dir, i, max_bytes) for i, u in enumerate(links, 1)]
    for r in results:
        if r.get("ok"):
            logs.append(_log("download", f"下載 {r['file']}（{r['size']} bytes）"))
        else:
            logs.append(_log("download", f"下載失敗 {r['url']}：{r.get('error')}", "error"))

    downloaded = sum(1 for r in results if r.get("ok"))
    set_tender_status(tid, "downloaded")
    logs.append(_log("download", f"文件取得完成：{downloaded}/{len(links)}"))
    return {"status": "downloaded", "logs": logs}


def _gather_docs(dossier: Path, logs: list[dict]) -> str:
    """收集 dossier 內文字（00_source.md + *.md/*.txt + PDF 文字抽取，PDF 用 PyMuPDF 若可用）。"""
    parts: list[str] = []
    source = dossier / "00_source.md"
    if source.exists():
        parts.append(source.read_text(encoding="utf-8"))
    docs = dossier / "docs"
    if docs.exists():
        for f in sorted(docs.iterdir()):
            if f.suffix.lower() in (".md", ".txt"):
                parts.append(f.read_text(encoding="utf-8", errors="replace"))
            elif f.suffix.lower() == ".pdf":
                try:
                    import fitz  # PyMuPDF（可選）
                    pdf_text = "\n".join(p.get_text() for p in fitz.open(f))
                    parts.append(f"[{f.name}]\n{pdf_text[:12000]}")
                except Exception:  # noqa: BLE001
                    logs.append(_log("digest", f"PDF 文字抽取失敗（缺 PyMuPDF？）：{f.name}", "warn"))
            else:
                logs.append(_log("digest", f"略過非文字檔：{f.name}", "warn"))
    return "\n\n".join(parts)


def _llm_digest(tender: dict, state: dict, context: str) -> str:
    """LLM 生成 01_digest.md；失敗時回退欄位式摘要。"""
    prompt = (
        "你是香港公開招標項目分析助手。根據資料，用正體中文寫一份結構化項目摘要（markdown）。\n"
        "必須包含章節：基本資料（招標編號/招標方/項目名稱/截止日期/地區）、範圍摘要、提交方式、"
        "資格要求（如有）、文件下載說明（如有）、資料來源。若資料不足，據實註明「未提供」。\n"
        f"招標資料：{json.dumps(tender, ensure_ascii=False)}\n"
        f"核實欄位：{json.dumps({k: state.get(k) for k in ('issuer', 'tender_no', 'deadline', 'official_url')}, ensure_ascii=False)}\n"
        f"文件內容（截斷）：\n{(context or '')[:12000]}\n"
    )
    try:
        from .llm import build_model
        model = build_model()
        resp = model.invoke([("system", "你是香港招標分析助手，輸出 markdown。"), ("human", prompt)])
        content = resp.content if isinstance(resp.content, str) else str(resp.content)
        return content.strip()
    except Exception as e:  # noqa: BLE001
        return (
            "# 項目摘要（自動回退，LLM 生成失敗）\n\n"
            f"- 招標編號：{state.get('tender_no') or tender.get('tender_ref')}\n"
            f"- 招標方：{state.get('issuer')}\n"
            f"- 項目名稱：{tender.get('title_en') or tender.get('title_zh')}\n"
            f"- 截止日期：{state.get('deadline') or tender.get('deadline')}\n"
            f"- 官方來源：{state.get('official_url') or '(未找到)'}\n\n"
            f"LLM 錯誤：{e}\n"
        )


def digest_node(state: dict) -> dict:
    logs: list[dict] = []
    tid = state["tender_id"]
    dossier = Path(state["dossier_dir"])
    tender = state["tender"]

    context = _gather_docs(dossier, logs)
    digest_md = _llm_digest(tender, state, context)
    (dossier / "01_digest.md").write_text(digest_md, encoding="utf-8")
    set_tender_status(tid, "digested")
    logs.append(_log("digest", "已生成 01_digest.md"))
    return {"status": "digested", "logs": logs}
