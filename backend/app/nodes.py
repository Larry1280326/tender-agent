"""Per-tender 節點邏輯：verify → digest。

沿用 services 做所有 fetching（reader/serper）；LLM 只做判斷同生成。
digest 係 agentic node：開一個子代理（search_web/read_page）補官方資料再生成 01_digest.md。
"""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import config
from .services import reader, serper
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


MAX_OFFICIAL_PAGES = 3
MAX_SEARCH_QUERIES = 3


def _rule_queries(tender: dict, extracted: dict) -> list[str]:
    """舊有 rule-based 關鍵字（LLM 失敗時回退）。"""
    tender_no = extracted.get("tender_no") or tender.get("tender_ref") or ""
    issuer = extracted.get("issuer") or ""
    title_en = tender.get("title_en") or ""
    title_zh = tender.get("title_zh") or ""
    return list(dict.fromkeys([q for q in [
        f"{tender_no} {issuer} 招標".strip(),
        f"{tender_no} {title_en}".strip(),
        f"{title_zh} 招標".strip(),
    ] if q.strip()]))


def _llm_make_queries(tender: dict, extracted: dict) -> list[str]:
    """LLM 決定搜尋關鍵字（1..MAX_SEARCH_QUERIES 條）；失敗回退 rule-based。"""
    try:
        from .llm import build_model
        model = build_model()
        prompt = (
            "你是香港公開招標項目分析助手。根據招標資料，設計最能搵到「官方招標通告」嘅搜尋關鍵字，"
            f"可含招標編號／招標方／項目名稱（中英皆可），最多 {MAX_SEARCH_QUERIES} 條。只輸出 JSON：{{\"queries\": [\"...\"]}}，勿加 markdown 框。\n"
            f"招標資料：{json.dumps(tender, ensure_ascii=False)}\n"
            f"Conneciz 詳情頁抽取：{json.dumps(extracted, ensure_ascii=False)}\n"
        )
        resp = model.invoke([("system", "你是香港招標分析助手，只輸出 JSON。"), ("human", prompt)])
        content = resp.content if isinstance(resp.content, str) else str(resp.content)
        data = json.loads(_strip_code_fences(content))
        queries = [q.strip() for q in (data.get("queries") or []) if q and q.strip()]
        queries = list(dict.fromkeys(queries))[:MAX_SEARCH_QUERIES]
        return queries or _rule_queries(tender, extracted)
    except Exception:  # noqa: BLE001
        return _rule_queries(tender, extracted)


def _rank_candidates(candidates: list[dict], limit: int = 10) -> list[dict]:
    """按 Serper 排序去重（by link），無 domain 偏好。"""
    seen: set[str] = set()
    out: list[dict] = []
    for r in sorted(candidates, key=lambda x: x.get("position", 99)):
        link = (r.get("link") or "").strip()
        if not link or link in seen:
            continue
        seen.add(link)
        out.append(r)
    return out[:limit]


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _llm_pick_pages(tender: dict, extracted: dict, candidates: list[dict]) -> list[str]:
    """LLM 由 Serper 候選揀要讀嘅頁（0..MAX_OFFICIAL_PAGES），取代 domain 偏好。失敗回退首位。"""
    links = {r.get("link"): r for r in candidates if r.get("link")}
    try:
        from .llm import build_model
        model = build_model()
        cand_lines = "\n".join(
            f"{i}. {r.get('title') or ''} — {r.get('link')}（{r.get('snippet') or ''}）"
            for i, r in enumerate(candidates, 1)
        )
        prompt = (
            "你是香港公開招標項目分析助手。以下係 Serper 搜尋候選結果，揀出最可能係「官方招標通告」嘅頁面，"
            f"可以揀 0–{MAX_OFFICIAL_PAGES} 個（揀多過一個係為咗互相核對）。只輸出 JSON：{{\"urls\": [\"...\"]}}，勿加 markdown 框。\n"
            f"招標資料：{json.dumps(tender, ensure_ascii=False)}\n"
            f"Conneciz 詳情頁抽取：{json.dumps(extracted, ensure_ascii=False)}\n"
            f"候選：\n{cand_lines}\n"
        )
        resp = model.invoke([("system", "你是香港招標分析助手，只輸出 JSON。"), ("human", prompt)])
        content = resp.content if isinstance(resp.content, str) else str(resp.content)
        data = json.loads(_strip_code_fences(content))
        urls = [u for u in (data.get("urls") or []) if u in links]
        return list(dict.fromkeys(urls))[:MAX_OFFICIAL_PAGES]
    except Exception as e:  # noqa: BLE001
        return [candidates[0]["link"]] if candidates else []


def _llm_judge(tender: dict, extracted: dict, pages: list[dict]) -> dict:
    """LLM 判斷地區/官方欄位（跨多頁）；失敗時回退 regex 抽取結果。"""
    try:
        from .llm import build_model
        model = build_model()
        page_lines = []
        budget = 6000
        per_page = max(budget // max(len(pages), 1), 500)
        for i, p in enumerate(pages, 1):
            page_lines.append(f"頁面 {i} URL：{p.get('url') or '(無)'}\n頁面 {i} 內容（截斷）：{(p.get('text') or '')[:per_page]}")
        prompt = (
            "你是香港公開招標項目分析助手。根據下方資料，判斷並輸出 JSON（只輸出 JSON，勿加 markdown 程式碼框）。\n"
            "JSON 鍵：region（如 HK/其他）、issuer（招標方）、tender_no（招標號碼）、deadline（截止日期）、"
            "doc_links（文件下載連結陣列）、official_url（最佳官方來源 URL，可空）、notes（一句話備註，可含時區/資料差異）。\n"
            "注意：deadline 欄位已為香港時間 HKT（UTC+8），勿再自行加 8 小時。\n"
            f"Conneciz 原始資料：{json.dumps(tender, ensure_ascii=False)}\n"
            f"Conneciz 詳情頁抽取：{json.dumps(extracted, ensure_ascii=False)}\n"
            + "\n".join(page_lines) + "\n"
        )
        resp = model.invoke([("system", "你是香港招標分析助手，只輸出 JSON。"), ("human", prompt)])
        content = resp.content if isinstance(resp.content, str) else str(resp.content)
        return json.loads(_strip_code_fences(content))
    except Exception as e:  # noqa: BLE001
        return {"region": "", "notes": f"LLM 判斷失敗（回退 regex）：{e}"}


def _write_source(dossier: Path, tender: dict, extracted: dict, pages: list[dict],
                  official_url: str, judgement: dict) -> str:
    lines = [
        "# 官方來源核實筆記",
        "",
        f"- 招標編號：{judgement.get('tender_no') or tender.get('tender_ref') or ''}",
        f"- 招標方：{judgement.get('issuer') or extracted.get('issuer') or ''}",
        f"- 截止日期：{judgement.get('deadline') or extracted.get('deadline') or tender.get('deadline') or ''}",
        f"- 地區：{judgement.get('region') or '未判定'}",
        f"- 官方來源：{official_url or '(未找到，以 Conneciz 為準)'}",
    ]
    if pages:
        lines += ["", "## 已讀頁面"]
        for i, p in enumerate(pages, 1):
            lines.append(f"{i}. {p.get('title') or p.get('url')} — {p.get('url')}")
    if judgement.get("notes"):
        lines += ["", f"備註：{judgement['notes']}"]
    lines += ["", "## Conneciz 原始資料", f"```json", json.dumps(tender, ensure_ascii=False, indent=2), "```"]
    text = "\n".join(lines)
    (dossier / "00_source.md").write_text(text, encoding="utf-8")
    return text


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

    # 搜尋官方來源（由 LLM 決定關鍵字）
    queries = _llm_make_queries(tender, extracted)
    candidates: list[dict] = []
    if config.SERPER_API_KEY:
        # 平行搜尋（每條關鍵字獨立打 Serper）
        def _search(q: str) -> tuple[str, list[dict] | None, str | None]:
            try:
                return q, serper.search(q, config.SERPER_API_KEY, num=10), None
            except Exception as e:  # noqa: BLE001
                return q, None, str(e)

        if queries:
            with ThreadPoolExecutor(max_workers=len(queries)) as ex:
                for q, res, err in ex.map(_search, queries):
                    if err is not None:
                        logs.append(_log("verify", f"Serper 搜尋失敗（{q}）：{err}", "error"))
                        continue
                    for r in res:
                        r["_query"] = q
                    candidates.extend(res)
                    logs.append(_log("verify", f"搜尋「{q}」：{len(res)} 條"))
    else:
        logs.append(_log("verify", "缺 SERPER_API_KEY，跳過官方搜尋", "warn"))

    doc_links = list(extracted.get("doc_links") or [])
    ranked = _rank_candidates(candidates)
    chosen = _llm_pick_pages(tender, extracted, ranked)
    title_by_link = {r.get("link"): r.get("title") for r in ranked}
    urls_to_fetch = [u for u in chosen if u and config.JINA_API_KEY]
    for u in urls_to_fetch:
        logs.append(_log("verify", f"LLM 揀咗讀取：{u}"))

    # 平行讀取官方頁面（Jina Reader 慢，逐頁打太耐）；apply 階段照 chosen 順序，保留「先到先得」語義
    fetched: dict[str, str] = {}
    fetch_errors: dict[str, str] = {}
    if urls_to_fetch:
        def _fetch_page(url: str) -> tuple[str, str | None, str | None]:
            try:
                return url, reader.read(url, config.JINA_API_KEY), None
            except Exception as e:  # noqa: BLE001
                return url, None, str(e)

        with ThreadPoolExecutor(max_workers=len(urls_to_fetch)) as ex:
            for url, text, err in ex.map(_fetch_page, urls_to_fetch):
                if err is not None:
                    fetch_errors[url] = err
                else:
                    fetched[url] = text

    pages: list[dict] = []
    for url in urls_to_fetch:
        if url in fetch_errors:
            logs.append(_log("verify", f"頁面讀取失敗：{url}：{fetch_errors[url]}", "warn"))
            continue
        text = fetched[url]
        off_ext = reader.extract(text)
        pages.append({
            "url": url,
            "title": title_by_link.get(url) or off_ext.get("title") or "",
            "text": text,
            "extracted": off_ext,
        })
        doc_links = list(off_ext.get("doc_links") or doc_links)
        tender_no = off_ext.get("tender_no") or tender_no
        issuer = off_ext.get("issuer") or issuer
        if not extracted.get("deadline"):
            extracted["deadline"] = off_ext.get("deadline")
    if not pages:
        logs.append(_log("verify", "LLM 冇揀要讀嘅頁，以 Conneciz 資料為準", "warn"))
    official_url = pages[0]["url"] if pages else ""

    judgement = _llm_judge(tender, extracted, pages)
    if judgement.get("official_url"):
        official_url = judgement["official_url"]
    source_md = _write_source(dossier, tender, extracted, pages, official_url, judgement)
    # 截止日以 LLM 官方交叉核實結果為準（judgement），冇先回退 Conneciz 抽取／原始值。
    final_deadline = judgement.get("deadline") or extracted.get("deadline") or tender.get("deadline", "")
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
        "source_md": source_md,
        "logs": logs,
    }


def _llm_digest(tender: dict, state: dict, context: str) -> str:
    """LLM 生成 01_digest.md；失敗時回退欄位式摘要。"""
    prompt = (
        "你是香港公開招標項目分析助手。根據資料，用正體中文寫一份結構化項目摘要（markdown）。\n"
        "必須包含章節：基本資料（招標編號/招標方/項目名稱/截止日期/地區）、範圍摘要、提交方式、"
        "資格要求（如有）、文件下載說明（如有）、資料來源。若資料不足，據實註明「未提供」。\n"
        "注意：deadline 欄位已為香港時間 HKT（UTC+8），直接採用即可。\n"
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


DIGEST_AGENT_PROMPT = (
    "你是香港公開招標項目分析助手。你會收到招標資料、核實欄位同核實筆記。\n"
    "你可以 call search_web / read_page 去補充官方招標通告內容（如有需要）。\n"
    "最後用正體中文寫一份結構化項目摘要（markdown），直接輸出 markdown，勿加任何前後說明或程式碼框。\n"
    "必須包含章節：基本資料（招標編號/招標方/項目名稱/截止日期/地區）、範圍摘要、提交方式、"
    "資格要求（如有）、文件下載說明（如有）、資料來源。若資料不足，據實註明「未提供」。\n"
    "注意：deadline 欄位已為香港時間 HKT（UTC+8），直接採用即可。\n"
)

_digest_agent = None


def _get_digest_agent():
    """digest 子代理（可 call search_web/read_page）；lazy 建立，無 checkpointer。"""
    global _digest_agent
    if _digest_agent is None:
        from langgraph.prebuilt import create_react_agent

        from .agent.web_tools import read_page, search_web
        from .llm import build_model

        _digest_agent = create_react_agent(
            build_model(), [search_web, read_page], prompt=DIGEST_AGENT_PROMPT
        )
    return _digest_agent


def _extract_text(content) -> str:
    """由 AIMessage content（str / list of blocks）抽純文字。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
        return "\n".join(parts)
    return str(content or "")


def _final_answer(messages) -> str:
    """攞 ReAct 子代理最後一個有文字嘅 AIMessage。"""
    for m in reversed(messages):
        if type(m).__name__ != "AIMessage":
            continue
        text = _extract_text(m.content).strip()
        if text:
            return text
    return ""


def _agentic_digest(tender: dict, state: dict, context: str) -> str:
    """digest 子代理生成摘要 markdown；失敗回退欄位式 _llm_digest。"""
    prompt = (
        f"招標資料：{json.dumps(tender, ensure_ascii=False)}\n"
        f"核實欄位：{json.dumps({k: state.get(k) for k in ('issuer', 'tender_no', 'deadline', 'official_url')}, ensure_ascii=False)}\n"
        f"核實筆記（00_source.md）：\n{context}\n"
    )
    try:
        agent = _get_digest_agent()
        result = agent.invoke({"messages": [("user", prompt)]})
        md = _final_answer(result.get("messages", []))
        return md or _llm_digest(tender, state, context)
    except Exception:  # noqa: BLE001
        return _llm_digest(tender, state, context)


def digest_node(state: dict) -> dict:
    logs: list[dict] = []
    tid = state["tender_id"]
    dossier = Path(state["dossier_dir"])
    tender = state["tender"]

    context = state.get("source_md") or ""
    if not context:
        source = dossier / "00_source.md"
        if source.exists():
            context = source.read_text(encoding="utf-8")

    digest_md = _agentic_digest(tender, state, context)
    (dossier / "01_digest.md").write_text(digest_md, encoding="utf-8")
    set_tender_status(tid, "digested")
    logs.append(_log("digest", "已生成 01_digest.md"))
    return {"status": "digested", "logs": logs, "digest_md": digest_md}
