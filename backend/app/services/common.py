"""共用工具：SSL fallback urlopen、UA、資料根目錄。供 services 內各模組共用。"""
from __future__ import annotations

import os
import ssl
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
