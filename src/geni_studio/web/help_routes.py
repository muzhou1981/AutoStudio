"""帮助正文与配图。正文在 `docs/help/`，每次请求重新读取，改完文档刷新页面即可看到。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from geni_studio.web.help_docs import ALIASES, HelpError, asset_path, load_topics

router = APIRouter(prefix="/api/help", tags=["help"])


@router.get("")
def api_help() -> dict:
    try:
        topics = load_topics()
    except HelpError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"topics": topics, "aliases": ALIASES}


@router.get("/assets/{name}")
def api_help_asset(name: str) -> FileResponse:
    path = asset_path(name)
    if path is None:
        raise HTTPException(status_code=404, detail="没有这张图。")
    return FileResponse(path, headers={"Cache-Control": "no-cache"})
