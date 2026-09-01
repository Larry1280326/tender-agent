"""招標列表 endpoint：香港非政府過濾列表（前端「選取項目」用）。"""
from __future__ import annotations

from fastapi import APIRouter

from .. import store
from ..classify import filter_non_gov

router = APIRouter()


@router.get("/tenders")
def list_tenders(scope: str = "non_gov"):
    tenders = store.list_tenders()
    if scope == "non_gov":
        tenders = filter_non_gov(tenders)
    return {"tenders": tenders}
