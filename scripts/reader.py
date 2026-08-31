#!/usr/bin/env python3
"""Jina Reader 讀頁：agent 叫嚟攞網頁內容（markdown），或抽取招標關鍵欄位。

用法:
    python3 scripts/reader.py --url <URL>              # 輸出整頁 markdown 內容
    python3 scripts/reader.py --url <URL> --extract    # 抽取招標方/招標號碼/截止日期等（JSON）

抽取欄位（Conneciz 詳情頁 + 官方通告頁通用，best-effort）:
    title（項目名稱）、issuer（招標方）、tender_no（招標號碼）、deadline（截止日期）、doc_links（文件連結）
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request

from common import UA, get_key, urlopen

JINA_READER = "https://r.jina.ai/"

# ── 抽取 regex（中文標籤專做 Conneciz 頁，英文標籤做官方通告頁） ─────────────

_RE_TITLE = re.compile(r"^Title\s*[:：]\s*(.+?)\s*$", re.MULTILINE)
_RE_ISSUER_ZH = re.compile(
    r"(?:招標方|招標機構|招標單位|招標部門|採購部門|採購機構|採購人|買方|機構名稱|招標人|採購單位)"
    r"\s*[:：.、]?\s*([^\n|]{1,80}?)(?=\s{2,}|\n|$)"
)
_RE_ISSUER_EN = re.compile(
    r"(?:Issuing\s*(?:Authority|Department|Office|Organisation|Organization|Agency|Body)|"
    r"Tendering\s*(?:Department|Authority|Entity|Body)|Procuring\s*(?:Department|Entity|Agency)|"
    r"Procurement\s*Department|Purchaser|Buyer)"
    r"\s*[:：]?\s*([A-Z][A-Za-z0-9 .&'()-]{2,80}?)(?=\s{2,}|\n|$)",
    re.IGNORECASE,
)
_RE_TENDER_NO_ZH = re.compile(r"(?:招標號碼|招標編號|投標編號|招標/投標編號)\s*[:：]?\s*([A-Za-z0-9][A-Za-z0-9/_-]{2,30})")
_RE_TENDER_NO_EN = re.compile(
    r"(?:Tender\s*(?:No\.?|Number|Reference|Ref\.?)|Reference\s*No\.?)\s*[:：]?\s*([A-Za-z0-9][A-Za-z0-9/_-]{2,30})",
    re.IGNORECASE,
)
_RE_DEADLINE_ZH = re.compile(
    r"(?:截止日期|截標日期|投標截止|截止時間)\s*[:：]?\s*(.{1,60}?)(?=\s{2,}|$|\n)"
)
_RE_DEADLINE_EN = re.compile(
    r"(?:Closing\s*(?:Date|Time)|Deadline|Tender\s*Closing|Closing\s*at)\s*[:：]?\s*(.{1,60}?)(?=\s{2,}|$|\n)",
    re.IGNORECASE,
)
_RE_DOC = re.compile(
    r"https?://[^\s<>\"'()]+\.(?:pdf|docx?|xlsx?|zip)(?:\?[^\s<>\"'()]*)?", re.IGNORECASE
)


def read(url: str, api_key: str) -> str:
    """Jina Reader 讀頁，回傳 markdown 內容。"""
    req = urllib.request.Request(
        JINA_READER + url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "User-Agent": UA,
            "X-Return-Format": "markdown",
        },
    )
    with urlopen(req, timeout=120) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _first(pattern: re.Pattern, text: str) -> str | None:
    m = pattern.search(text)
    return m.group(1).strip(" \t:：.、,，") if m else None


def extract(text: str) -> dict:
    text = text or ""
    deadline = _first(_RE_DEADLINE_ZH, text) or _first(_RE_DEADLINE_EN, text)
    if deadline and not re.search(r"\d", deadline):  # 例如「(Hong Kong Time)」欄頭，唔係真日期
        deadline = None
    return {
        "title": _first(_RE_TITLE, text),
        "issuer": _first(_RE_ISSUER_ZH, text) or _first(_RE_ISSUER_EN, text),
        "tender_no": _first(_RE_TENDER_NO_ZH, text) or _first(_RE_TENDER_NO_EN, text),
        "deadline": deadline,
        "doc_links": list(dict.fromkeys(_RE_DOC.findall(text)))[:20],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Jina Reader 讀頁")
    ap.add_argument("--url", required=True, help="要讀嘅 URL")
    ap.add_argument("--extract", action="store_true", help="抽取招標欄位（JSON）而非輸出全文")
    ap.add_argument("--max-chars", type=int, default=0, help="全文截斷字數（0 = 唔截）")
    args = ap.parse_args()

    key = get_key("JINA_API_KEY")
    if not key:
        print("缺 JINA_API_KEY（放 .env）", file=sys.stderr)
        return 1

    text = read(args.url, key)

    if args.extract:
        print(json.dumps({"url": args.url, "chars": len(text), **extract(text)},
                         ensure_ascii=False, indent=2))
    else:
        out = text if args.max_chars <= 0 else text[: args.max_chars]
        print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
