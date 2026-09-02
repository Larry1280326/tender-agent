"""上傳檔案端點：用戶手動下載招標文件後，上傳俾 agent 用 read_file 讀。

有綁定 tender 就存去該招標 dossier 嘅 docs/，否則存去 data/uploads/<thread_id>/。
回傳相對 DATA_DIR 嘅路徑，前端再將佢寫入 chat 訊息交俾 read_file。
"""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, UploadFile

from .. import sessions, store
from ..schemas import UploadResponse
from ..services import utils

router = APIRouter()

MAX_UPLOAD_BYTES = 100 * 1024 * 1024
CHUNK = 64 * 1024


@router.post("/upload", response_model=UploadResponse)
async def upload_file(file: UploadFile, thread_id: str = Form("default")):
    name = utils._safe_name(file.filename or "upload")
    ext = os.path.splitext(name)[1].lower()
    if ext not in utils.ALLOWED_EXTENSIONS:
        allowed = " / ".join(sorted(utils.ALLOWED_EXTENSIONS))
        raise HTTPException(status_code=400, detail=f"不支援嘅副檔名：{ext or '(無)'}（只支援 {allowed}）。")

    sess = sessions.get_session(thread_id)
    tender_id = (sess or {}).get("tender_id") or ""
    if tender_id and store.get_tender(tender_id) is not None:
        dest = store.dossier_dir(tender_id) / "docs"
    else:
        dest = store.DATA_DIR / "uploads" / thread_id
    dest.mkdir(parents=True, exist_ok=True)

    target = dest / name
    if target.exists():
        stem, ext2 = os.path.splitext(name)
        target = dest / f"{stem}-1{ext2}"
    tmp = target.with_name(target.name + ".part")
    size = 0
    try:
        with open(tmp, "wb") as f:
            while chunk := await file.read(CHUNK):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="檔案過大（上限 100 MB）。")
                f.write(chunk)
        tmp.replace(target)
    finally:
        tmp.unlink(missing_ok=True)
        await file.close()

    rel = target.relative_to(store.DATA_DIR)
    return UploadResponse(path=rel.as_posix(), filename=target.name, size=size)
