#!/usr/bin/env python3
"""Serper Google 搜尋：agent 叫嚟攞搜尋結果（標題 + 網址 + 摘要）。

用法:
    python3 scripts/serper.py --query "PTCSQ00524 懲教署 招標"
    python3 scripts/serper.py --query "..." --num 10 --gl hk --hl zh-Hant

輸出 JSON:
    {"query": "...", "results": [{"title", "link", "snippet", "position"}]}
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request

from common import UA, get_key, urlopen

SERPER_URL = "https://google.serper.dev/search"


def search(query: str, api_key: str, num: int = 10, gl: str = "hk", hl: str = "zh-Hant") -> list[dict]:
    """Serper Google 搜尋，回傳 organic 結果（title/link/snippet/position）。"""
    payload = json.dumps({"q": query, "gl": gl, "hl": hl, "num": num}).encode("utf-8")
    req = urllib.request.Request(
        SERPER_URL,
        data=payload,
        headers={
            "X-API-KEY": api_key,
            "Content-Type": "application/json",
            "User-Agent": UA,
            "Accept": "application/json",
        },
        method="POST",
    )
    with urlopen(req) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    out: list[dict] = []
    for it in body.get("organic") or []:
        out.append({
            "title": it.get("title") or "",
            "link": it.get("link") or "",
            "snippet": it.get("snippet") or "",
            "position": it.get("position"),
        })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Serper Google 搜尋")
    ap.add_argument("--query", "-q", required=True, help="搜尋字串")
    ap.add_argument("--num", type=int, default=10, help="結果數量（預設 10）")
    ap.add_argument("--gl", default="hk", help="地區（預設 hk）")
    ap.add_argument("--hl", default="zh-Hant", help="語言（預設 zh-Hant）")
    args = ap.parse_args()

    key = get_key("SERPER_API_KEY")
    if not key:
        print("缺 SERPER_API_KEY（放 .env）", file=sys.stderr)
        return 1

    results = search(args.query, key, args.num, args.gl, args.hl)
    print(json.dumps({"query": args.query, "results": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
