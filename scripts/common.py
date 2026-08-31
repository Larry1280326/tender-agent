#!/usr/bin/env python3
"""共用工具：.env 讀取、SSL fallback urlopen、UA。供 serper.py / reader.py 共用。"""
from __future__ import annotations

import os
import ssl
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36 tender-pipeline"

# SSL 證書：預設 context 失敗時退回 macOS 系統根證書（同 discover.py）
_SSL_CONTEXTS = [ssl.create_default_context()]
for _cafile in ("/etc/ssl/cert.pem",):
    if Path(_cafile).exists():
        _SSL_CONTEXTS.append(ssl.create_default_context(cafile=_cafile))


def load_env() -> dict[str, str]:
    """讀 .env（KEY=VALUE，支援 # 註解、引號）。"""
    env: dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def get_key(name: str) -> str:
    """shell 環境變數優先，其次 .env。"""
    return os.environ.get(name) or load_env().get(name, "")


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
