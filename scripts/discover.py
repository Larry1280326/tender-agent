#!/usr/bin/env python3
"""Conneciz 公開 API 招標發現腳本（零登入，純標準庫）。

用法:
    python3 scripts/discover.py                  # 增量檢查，輸出 JSON
    python3 scripts/discover.py --baseline       # 重設基線（過去 N 日視為「已見」）
    python3 scripts/discover.py --since <ts>     # 手動 watermark（測試用，不改狀態 watermark）
    python3 scripts/discover.py --lookback-days 7   # 基線回望日數（預設 7，只喺 --baseline 生效）

stdout JSON 結構:
    {"run": {...}, "new": [...], "updated": N}
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import ssl
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

API = "https://conneciz.app/api/1.1/obj/tender"
STATE_FILE = Path(__file__).resolve().parent.parent / "pipeline_state.json"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36 tender-pipeline"
PAGE_SIZE = 100
MAX_PAGES = 30  # 安全上限，防止無限迴圈

# SSL 證書：預設 context 失敗時退回 macOS 系統根證書
# （python.org 安裝嘅 Python 有時搵唔到系統 CA）
_SSL_CONTEXTS = [ssl.create_default_context()]
for _cafile in ("/etc/ssl/cert.pem",):
    if Path(_cafile).exists():
        _SSL_CONTEXTS.append(ssl.create_default_context(cafile=_cafile))


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def fetch_page(since: str | None, limit: int = PAGE_SIZE) -> list[dict]:
    """攞一頁記錄：Modified Date > since，按 Modified Date 遞減排序。"""
    params = {
        "limit": str(limit),
        "sort_field": "ClosingDateTime",
        "descending": "true",
    }
    if since:
        constraints = json.dumps(
            [{"key": "Modified Date", "constraint_type": "greater than", "value": since}],
            ensure_ascii=False,
        )
        params["constraints"] = constraints
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
            # SSL 驗證失敗 → 換證書 bundle 重試；其他網絡錯誤直接拋出
            if isinstance(e.reason, ssl.SSLCertVerificationError):
                last_err = e.reason
                continue
            raise
    raise last_err  # type: ignore[misc]


def iter_since(since: str | None) -> list[dict]:
    """攞晒 Modified Date > since 嘅記錄（watermark 分頁：本頁最舊時間作下一頁基準）。"""
    out: list[dict] = []
    seen_ids: set[str] = set()
    cur = since
    for _ in range(MAX_PAGES):
        page = fetch_page(cur)
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


def load_state() -> dict:
    if STATE_FILE.exists():
        state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        # 遷移：統一為 {first_seen, url, title_en, title_zh}
        seen = state.get("tenders_seen", {})
        migrated = {}
        for rid, v in seen.items():
            if isinstance(v, str):
                migrated[rid] = {"first_seen": v, "url": "", "title_en": "", "title_zh": ""}
            elif isinstance(v, dict):
                migrated[rid] = {
                    "first_seen": v.get("first_seen", v.get("modified", "")),
                    "url": v.get("url", ""),
                    "title_en": v.get("title_en", ""),
                    "title_zh": v.get("title_zh", ""),
                }
        state["tenders_seen"] = migrated
        return state
    return {"tenders_seen": {}, "watermark_ts": None, "baseline_ts": None}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_name(STATE_FILE.name + ".tmp")
    tmp.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(tmp, STATE_FILE)


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
        "url": f"https://conneciz.app/view-tender/{slug}" if slug else "",
    }


def seen_entry(rec: dict, first_seen: str) -> dict:
    """已見記錄：只保留 first_seen + url + 標題。"""
    slug = rec.get("Slug") or ""
    return {
        "first_seen": first_seen,
        "url": f"https://conneciz.app/view-tender/{slug}" if slug else "",
        "title_en": (rec.get("Subject_EN") or "").strip(),
        "title_zh": (rec.get("Subject_ZH") or "").strip(),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Conneciz 公開 API 招標發現")
    ap.add_argument("--baseline", action="store_true", help="重設基線")
    ap.add_argument("--since", default=None, help="手動 watermark（ISO ts，測試用）")
    ap.add_argument("--lookback-days", type=int, default=7, help="基線回望日數")
    args = ap.parse_args()

    state = load_state()
    run_ts = now_iso()

    # ── 基線模式：過去 N 日記錄一律視為「已見」，不報新項目 ──
    if args.baseline or not state.get("watermark_ts"):
        since = args.since or (
            datetime.now(timezone.utc) - timedelta(days=args.lookback_days)
        ).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        records = iter_since(since)
        for rec in records:
            rid = record_id(rec)
            state["tenders_seen"][rid] = seen_entry(rec, rec.get("Modified Date") or "")
        watermark = max((r.get("Modified Date", "") for r in records), default=since)
        state["watermark_ts"] = watermark
        state["baseline_ts"] = run_ts
        save_state(state)
        print(json.dumps({
            "run": {"mode": "baseline", "at": run_ts, "since": since,
                    "fetched": len(records), "watermark": watermark},
            "new": [],
            "updated": 0,
        }, ensure_ascii=False, indent=2))
        return 0

    # ── 增量模式 ──
    since = args.since or state["watermark_ts"]
    records = iter_since(since)
    new_records: list[dict] = []
    updated = 0
    max_mt = since or ""
    for rec in records:
        rid = record_id(rec)
        s = slim(rec)
        if rid in state["tenders_seen"]:
            # 刷新 url／標題（保留 first_seen）
            first_seen = state["tenders_seen"][rid].get("first_seen", "")
            state["tenders_seen"][rid] = seen_entry(rec, first_seen)
            updated += 1
        else:
            s["first_seen"] = run_ts
            state["tenders_seen"][rid] = seen_entry(rec, run_ts)
            new_records.append(s)
        if (rec.get("Modified Date") or "") > max_mt:
            max_mt = rec.get("Modified Date") or ""
    # 只喺正常 run（無 --since override）先推前 watermark
    if not args.since and max_mt != since:
        state["watermark_ts"] = max_mt
    # 冇變化就唔寫檔（避免每日空跑都重寫成個 JSON）
    if new_records or updated:
        save_state(state)

    print(json.dumps({
        "run": {"mode": "incremental", "at": run_ts, "since": since,
                "fetched": len(records)},
        "new": new_records,
        "updated": updated,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
