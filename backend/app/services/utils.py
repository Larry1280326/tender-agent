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


def download(url: str, dest_dir: Path, idx: int, max_bytes: int) -> dict:
    """下載一個 URL 到 dest_dir（stream 落 .part，成功先 os.replace，附 SHA1）。"""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urlopen(req, timeout=120) as resp:
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
