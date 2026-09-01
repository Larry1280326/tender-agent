"""Serper Google 搜尋：agent 叫嚟攞搜尋結果（標題 + 網址 + 摘要）。"""
from __future__ import annotations

import json
import urllib.request

from .common import UA, urlopen

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
