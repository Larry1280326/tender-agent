#!/usr/bin/env python3
"""狀態工具：列出／批量修改 pipeline_state.json 招標處理狀態 + 下載招標文件（C1）。

用法:
    python3 scripts/utils.py --list                              # 唯讀列出已見招標
    python3 scripts/utils.py --set-status <status> --ids <id1> [id2 ...]
    python3 scripts/utils.py --download <id> --urls <u1> [u2 ...]   # 下載文件到 dossiers/<id>/docs/

status 必須係: discovered | searched | downloaded | digested
（攞 _id 用 `python3 scripts/utils.py --list`。）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from common import UA, urlopen
from discover import DEFAULT_STATUS, STATUSES, load_state, now_iso, save_state

ROOT = Path(__file__).resolve().parent.parent
DOSSIERS = ROOT / "dossiers"
CHUNK = 64 * 1024
DEFAULT_MAX_MB = 100

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


def set_statuses(state: dict, ids: list[str], status: str, ts: str) -> dict:
    """批量設定狀態；逐個 id 回報結果，只統計成功數。"""
    results = []
    changed = 0
    for rid in ids:
        entry = state.get("tenders_seen", {}).get(rid)
        if entry is None:
            results.append({"id": rid, "ok": False, "error": "not found"})
        else:
            entry["status"] = status
            entry["status_at"] = ts
            results.append({"id": rid, "ok": True})
            changed += 1
    return {"results": results, "changed": changed, "requested": len(ids)}


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


def do_download(tender_id: str, urls: list[str], max_mb: int) -> int:
    """下載一組文件 URL 到 dossiers/<tender_id>/docs/。"""
    if not tender_id or "/" in tender_id or "\\" in tender_id or tender_id in (".", ".."):
        print(json.dumps({"error": f"invalid tender id: {tender_id!r}"}, ensure_ascii=False))
        return 1
    dest_dir = DOSSIERS / tender_id / "docs"
    dest_dir.mkdir(parents=True, exist_ok=True)
    max_bytes = max_mb * 1024 * 1024
    results = [download(u, dest_dir, i, max_bytes) for i, u in enumerate(urls, 1)]
    downloaded = sum(1 for r in results if r.get("ok"))
    print(json.dumps({
        "tender_id": tender_id,
        "dir": str(dest_dir),
        "results": results,
        "downloaded": downloaded,
        "requested": len(urls),
    }, ensure_ascii=False, indent=2))
    return 0 if downloaded == len(urls) else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="狀態工具：列出／批量改狀態／下載招標文件")
    ap.add_argument("--list", action="store_true", help="唯讀列出已見招標（唔改狀態）")
    ap.add_argument("--set-status", dest="status", metavar="STATUS",
                    help="要設定嘅狀態（discovered|searched|downloaded|digested）")
    ap.add_argument("--ids", nargs="+", metavar="ID", help="一個或多個招標 _id（配合 --set-status）")
    ap.add_argument("--download", metavar="TENDER_ID", help="下載招標文件（配合 --urls）")
    ap.add_argument("--urls", nargs="+", metavar="URL", help="一個或多個文件 URL（配合 --download）")
    ap.add_argument("--max-mb", type=int, default=DEFAULT_MAX_MB, help="單檔大小上限 MB（預設 100）")
    args = ap.parse_args()

    # ── 下載（C1） ──
    if args.download:
        if not args.urls:
            ap.error("--download 需要配合 --urls")
        return do_download(args.download, args.urls, args.max_mb)

    state = load_state()

    if args.list:
        print(json.dumps(list_state(state), ensure_ascii=False, indent=2))
        return 0

    if not args.status:
        ap.error("需要 --set-status（配合 --ids）、--download（配合 --urls）或 --list")
    if args.status not in STATUSES:
        print(json.dumps({"error": f"status 必須係 {list(STATUSES)}"}, ensure_ascii=False))
        return 1
    if not args.ids:
        ap.error("需要 --ids")

    ts = now_iso()
    report = set_statuses(state, args.ids, args.status, ts)
    if report["changed"]:
        save_state(state)

    print(json.dumps({
        "status": args.status,
        "status_at": ts,
        "results": report["results"],
        "changed": report["changed"],
        "requested": report["requested"],
    }, ensure_ascii=False, indent=2))
    return 0 if report["changed"] == report["requested"] else 1


if __name__ == "__main__":
    sys.exit(main())
