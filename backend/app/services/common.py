"""共用工具：SSL fallback urlopen、UA、資料根目錄。供 services 內各模組共用。"""
from __future__ import annotations

import json
import os
import ssl
import time
import urllib.request
from pathlib import Path

# backend/ 根目錄（此檔喺 backend/app/services/common.py）
ROOT = Path(__file__).resolve().parent.parent.parent
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36 tender-pipeline"


def data_root() -> Path:
    """資料根目錄：TENDER_DATA_DIR 環境變數優先，否則 backend/data。"""
    env = os.environ.get("TENDER_DATA_DIR")
    return Path(env).resolve() if env else (ROOT / "data")


# SSL 證書：預設 context 失敗時退回 macOS 系統根證書
_SSL_CONTEXTS = [ssl.create_default_context()]
for _cafile in ("/etc/ssl/cert.pem",):
    if Path(_cafile).exists():
        _SSL_CONTEXTS.append(ssl.create_default_context(cafile=_cafile))


def urlopen(req: urllib.request.Request, timeout: int = 60):
    """urlopen，附 SSL 證書 fallback（SSLCertVerificationError → 換 bundle 重試）。"""
    last_err = None
    for ctx in _SSL_CONTEXTS:
        try:
            return urllib.request.urlopen(req, timeout=timeout, context=ctx)
        except urllib.error.URLError as e:
            if isinstance(e.reason, ssl.SSLCertVerificationError):
                last_err = e.reason
                continue
            raise
    raise last_err  # type: ignore[misc]


class TTLCache:
    """極簡 TTL cache：`ttl` 秒後過期，超過 `maxsize` 用 FIFO 逐出。

    只 cache 非空值（caller 負責：空 = rate-limit／失敗，唔好 cache 以免卡死一段時間）。
    """

    def __init__(self, ttl: float = 300.0, maxsize: int = 256):
        self.ttl = ttl
        self.maxsize = maxsize
        self._data: dict = {}

    def get(self, key):
        item = self._data.get(key)
        if item is None:
            return None
        value, at = item
        if time.monotonic() - at > self.ttl:
            del self._data[key]
            return None
        return value

    def set(self, key, value) -> None:
        self._data[key] = (value, time.monotonic())
        if len(self._data) > self.maxsize:
            oldest = next(iter(self._data))
            self._data.pop(oldest, None)


def markdown_result(summary: str, docs: list[dict] | None) -> str:
    """tool 回傳：summary 俾 LLM 睇，docs（[{title, content}]）俾 frontend 渲染。"""
    if not docs:
        return summary
    return json.dumps({"summary": summary, "docs": docs}, ensure_ascii=False)


def parse_markdown_result(text: str) -> tuple[str, list[dict] | None]:
    """反解 markdown_result；非 JSON 就原樣回傳 (text, None)。

    同時接受舊版 "markdown" 欄位（單一 markdown 字串），包裝成 docs=[{title, content}]，
    等已記錄嘅 session 歷史仍可渲染。
    """
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            summary = data.get("summary") or ""
            if "docs" in data:
                docs = data.get("docs")
                if isinstance(docs, list):
                    return summary, [d for d in docs if isinstance(d, dict)] or None
                return summary, None
            if "markdown" in data:
                markdown = data.get("markdown")
                return summary, [{"title": "Markdown", "content": markdown}] if markdown else None
    except (json.JSONDecodeError, TypeError):
        pass
    return (text or "").strip() if isinstance(text, str) else str(text), None
