"""Conneciz 公開 API 招標發現（零登入，純標準庫）。

backend 內嘅版本：冇 CLI，只提供函數。每次「發現」都係即時讀取，冇 watermark／基線／增量。
"""
from __future__ import annotations

import hashlib
import json
import ssl
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

API = "https://conneciz.app/api/1.1/obj/tender?loct=HK"

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36 tender-pipeline"
PAGE_SIZE = 100
MAX_PAGES = 3  # 列表頁數上限（純「列表」用，唔再跑全量掃描）
DEFAULT_STATUS = "discovered"

# SSL 證書：預設 context 失敗時退回 macOS 系統根證書
_SSL_CONTEXTS = [ssl.create_default_context()]
for _cafile in ("/etc/ssl/cert.pem",):
    if Path(_cafile).exists():
        _SSL_CONTEXTS.append(ssl.create_default_context(cafile=_cafile))


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def fetch_page(
    since: str | None,
    limit: int = PAGE_SIZE,
    deadline_min: str | None = None,
    deadline_max: str | None = None,
) -> list[dict]:
    """攞一頁記錄：Modified Date > since（且截止日在 [deadline_min, deadline_max] 內），
    按 ClosingDateTime 遞減排序。"""
    params = {
        "limit": str(limit),
        "sort_field": "ClosingDateTime",
        "descending": "True",
    }
    constraints = []
    if since:
        constraints.append(
            {"key": "Modified Date", "constraint_type": "greater than", "value": since}
        )
    if deadline_min:
        constraints.append(
            {"key": "ClosingDateTime", "constraint_type": "greater than", "value": deadline_min}
        )
    if deadline_max:
        constraints.append(
            {"key": "ClosingDateTime", "constraint_type": "less than", "value": deadline_max}
        )
    if constraints:
        params["constraints"] = json.dumps(constraints, ensure_ascii=False)
    url = f"{API}?{urllib.parse.urlencode(params, quote_via=urllib.parse.quote)}"
    last_err = None
    for ctx in _SSL_CONTEXTS:
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": UA, "Accept": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            return body.get("response", {}).get("results") or []
        except urllib.error.URLError as e:
            if isinstance(e.reason, ssl.SSLCertVerificationError):
                last_err = e.reason
                continue
            raise
    raise last_err  # type: ignore[misc]


def iter_since(
    since: str | None,
    deadline_min: str | None = None,
    deadline_max: str | None = None,
    max_pages: int = MAX_PAGES,
) -> list[dict]:
    """攞晒 Modified Date > since 嘅記錄（用 Modified Date 做分頁游標）。"""
    out: list[dict] = []
    seen_ids: set[str] = set()
    cur = since
    for _ in range(max_pages):
        page = fetch_page(cur, deadline_min=deadline_min, deadline_max=deadline_max)
        if not page:
            break
        fresh = [r for r in page if r.get("_id") not in seen_ids]
        if not fresh:
            break
        for r in fresh:
            seen_ids.add(r.get("_id"))
        out.extend(fresh)
        if len(page) < PAGE_SIZE:
            break
        mtimes = [r.get("Modified Date", "") for r in fresh if r.get("Modified Date")]
        if not mtimes:
            break
        cur = min(mtimes)
        time.sleep(0.3)  # 禮貌限速
    return out


def record_id(rec: dict) -> str:
    rid = rec.get("_id")
    if rid:
        return rid
    return hashlib.sha1(
        f"{rec.get('Tender_No','')}|{rec.get('Subject_EN','')}".encode("utf-8")
    ).hexdigest()


def slim(rec: dict) -> dict:
    """只保留 pipeline 需要嘅字段。"""
    slug = rec.get("Slug") or ""
    return {
        "_id": rec.get("_id"),
        "tender_ref": rec.get("Tender_No") or "",
        "title_en": (rec.get("Subject_EN") or "").strip(),
        "title_zh": (rec.get("Subject_ZH") or "").strip(),
        "category": rec.get("Tender Category") or "",
        "created": rec.get("Created Date") or "",
        "modified": rec.get("Modified Date") or "",
        "deadline": rec.get("ClosingDateTime") or "",
        "url": f"https://conneciz.app/view-tender/{slug}" if slug else "",
    }


def fetch_tenders(
    min_days_ahead: int = 2,
    max_days_ahead: int = 365,
    max_pages: int = MAX_PAGES,
) -> list[dict]:
    """即時讀取 Conneciz 列表：截止日在 [now+min, now+max] 內，按 ClosingDateTime 遞減。

    冇基線／增量／watermark —— 純粹攞列表俾用戶揀項目。
    """
    now = datetime.now(timezone.utc)
    deadline_min = (now + timedelta(days=min_days_ahead)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    deadline_max = (now + timedelta(days=max_days_ahead)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    records = iter_since(None, deadline_min, deadline_max, max_pages=max_pages)
    slims = [slim(r) for r in records]
    slims.sort(key=lambda r: r.get("deadline") or "", reverse=True)
    return slims
