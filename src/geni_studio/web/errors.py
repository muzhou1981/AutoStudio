"""业务异常到 HTTP 状态码的统一映射。"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from geni_studio.config.context import ConfigNotFound
from geni_studio.hitl.service import RunConflict, RunNotFound


def status_for(exc: Exception, default: int = 400) -> int:
    if isinstance(exc, (RunNotFound, ConfigNotFound)):
        return 404
    if isinstance(exc, RunConflict):
        return 409
    return default


def http_error(exc: Exception, default: int = 400) -> HTTPException:
    return HTTPException(status_code=status_for(exc, default), detail=str(exc))


def install_handlers(app: FastAPI) -> None:
    """未在路由中捕获的业务异常也按类型返回状态码。"""

    async def handle(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status_for(exc), content={"detail": str(exc)})

    for kind in (RunNotFound, RunConflict, ConfigNotFound):
        app.add_exception_handler(kind, handle)
