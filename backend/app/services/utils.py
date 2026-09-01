"""狀態／下載工具：列出已見招標 + 下載招標文件。"""
from __future__ import annotations

import hashlib
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

from .common import UA, data_root, urlopen
from .conneciz import DEFAULT_STATUS, now_iso

DOSSIERS = data_root() / "dossiers"
CHUNK = 64 * 1024

# Content-Type → 副檔名（URL 無副檔名時靠呢個估）
_CT_EXT = {
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/zip": ".zip",
}


def list_state(state: dict) -> dict:
    """唯讀 snapshot：已見招標列表（最新在前）+ 狀態摘要。"""
    entries = [
        {
            "_id": rid,
            "first_seen": entry.get("first_seen", ""),
            "url": entry.get("url", ""),
            "title_en": entry.get("title_en", ""),
            "title_zh": entry.get("title_zh", ""),
            "tender_ref": entry.get("tender_ref", ""),
            "category": entry.get("category", ""),
            "deadline": entry.get("deadline", ""),
            "status": entry.get("status", DEFAULT_STATUS),
            "status_at": entry.get("status_at", ""),
        }
        for rid, entry in state.get("tenders_seen", {}).items()
    ]
    entries.sort(key=lambda e: e.get("first_seen", ""), reverse=True)
    return {
        "mode": "list",
        "at": now_iso(),
        "count": len(entries),
        "watermark_ts": state.get("watermark_ts"),
        "baseline_ts": state.get("baseline_ts"),
        "tenders_seen": entries,
    }


def _filename(url: str, resp, idx: int) -> str:
    """由 Content-Disposition → URL path → Content-Type 推檔名。"""
    cd = resp.headers.get("Content-Disposition", "")
    m = re.search(r"filename\*?=([^;]+)", cd, re.IGNORECASE)
    if m:
        raw = re.sub(r"^[A-Za-z0-9_.-]+''", "", m.group(1).strip().strip('"'))
        raw = urllib.parse.unquote(raw).strip()
        if raw:
            return os.path.basename(raw)
    base = os.path.basename(urllib.parse.urlparse(url).path)
    if base:
        return urllib.parse.unquote(base)
    ct = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    return f"download_{idx}{_CT_EXT.get(ct, '')}"


def _safe_name(name: str) -> str:
    name = name.strip().replace("/", "_").replace("\\", "_")
    return name or "download"


# HTML client-side redirect（JS / meta refresh）判定。urlopen 只跟 HTTP 3xx，
# 唔會執行 JS，所以一啲內容伺服器（如 HA ha_view_content.asp）回傳 HTML 內藏
# window.open('/xxx.pdf') 就唔會落到檔。
_HTML_EXT = (".asp", ".aspx", ".php", ".jsp", ".html", ".htm", ".do")
MAX_HTML_REDIRECTS = 5
_MAX_HTML_BYTES = 2 * 1024 * 1024

_JS_REDIRECT_RE = re.compile(
    r"(?:window\.open|window\.location|document\.location|location)"
    r"(?:\s*\.\s*(?:href|replace|assign))?"
    r"\s*(?:=|\()\s*['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)
_META_REFRESH_RE = re.compile(
    r"<meta[^>]+content\s*=\s*['\"][^'\"]*url\s*=\s*([^'\";\s>]+)",
    re.IGNORECASE,
)


def _html_redirect_target(body: bytes, final_url: str) -> str | None:
    """由 HTML body 抽 client-side redirect 目標，回傳絕對 URL 或 None。"""
    text = body.decode("utf-8", errors="replace")
    m = _JS_REDIRECT_RE.search(text) or _META_REFRESH_RE.search(text)
    if m:
        return urllib.parse.urljoin(final_url, m.group(1).strip())
    return None


def _ha_lang_retry(url: str, text: str) -> str | None:
    """HA ha_view_content.asp：CHI 版回傳 404 頁時改試 ENG 版（同一 content_id）。"""
    if "ha_view_content.asp" not in url:
        return None
    if not re.search(r"404|does not exist|not found", text, re.IGNORECASE):
        return None
    parts = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(parts.query)
    if (qs.get("lang") or [""])[0].upper() == "ENG":
        return None
    qs["lang"] = ["ENG"]
    return urllib.parse.urlunparse(parts._replace(query=urllib.parse.urlencode(qs, doseq=True)))


def download(url: str, dest_dir: Path, idx: int, max_bytes: int, _depth: int = 0) -> dict:
    """下載一個 URL 到 dest_dir（stream 落 .part，成功先 os.replace，附 SHA1）。

    會跟住 HTTP 3xx（urlopen 自動）同 HTML client-side redirect（JS/meta），
    HA ha_view_content.asp 嘅 CHI 版 404 頁會改試 ENG。
    """
    if _depth > MAX_HTML_REDIRECTS:
        return {"url": url, "ok": False, "error": f"redirect 超過 {MAX_HTML_REDIRECTS} 層"}
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urlopen(req, timeout=120) as resp:
            final_url = resp.geturl()
            ct = (resp.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            path = urllib.parse.urlparse(final_url).path.lower()
            is_html = ct.startswith("text/html") or path.endswith(_HTML_EXT)
            if is_html:
                body = resp.read(_MAX_HTML_BYTES)
                target = _html_redirect_target(body, final_url)
                if target:
                    return download(target, dest_dir, idx, max_bytes, _depth + 1)
                retry = _ha_lang_retry(final_url, body.decode("utf-8", errors="replace"))
                if retry:
                    return download(retry, dest_dir, idx, max_bytes, _depth + 1)
                return {"url": url, "ok": False, "error": "回應係 HTML 頁（非文件，可能需登入／JS 跳轉）"}
            name = _safe_name(_filename(url, resp, idx))
            dest = dest_dir / name
            if dest.exists():  # 同批檔名撞名 → 加 -<idx> 避免覆蓋
                stem, ext = os.path.splitext(name)
                name = f"{stem}-{idx}{ext}"
                dest = dest_dir / name
            tmp = dest.with_name(name + ".part")
            h = hashlib.sha1()
            size = 0
            ok = True
            with open(tmp, "wb") as f:
                for chunk in iter(lambda: resp.read(CHUNK), b""):
                    size += len(chunk)
                    if size > max_bytes:
                        ok = False
                        break
                    f.write(chunk)
                    h.update(chunk)
            if not ok:
                tmp.unlink(missing_ok=True)
                return {"url": url, "ok": False, "error": f"exceeds max {max_bytes} bytes"}
            os.replace(tmp, dest)
            return {"url": url, "ok": True, "file": name, "size": size, "sha1": h.hexdigest()}
    except Exception as e:  # 逐檔獨立回報，唔中止成批
        return {"url": url, "ok": False, "error": str(e)}
