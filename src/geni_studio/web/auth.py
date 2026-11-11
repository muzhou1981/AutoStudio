"""Web 访问令牌与操作者身份。

设置 `GENI_STUDIO_WEB_TOKEN` 后，`/api/*`（飞书回调除外，另有回调令牌）须携带令牌：
请求头 `X-Geni-Studio-Token`、`Authorization: Bearer <令牌>`，或 Cookie `geni_studio_token`。
浏览器首次打开 `/?token=<令牌>` 时写入 Cookie。
"""

from __future__ import annotations

import ipaddress
import os
import secrets

from fastapi import Request
from fastapi.responses import JSONResponse

COOKIE = "geni_studio_token"
HEADER = "x-geni-studio-token"


def web_token() -> str:
    return os.environ.get("GENI_STUDIO_WEB_TOKEN", "").strip()


def web_operator() -> str:
    """Web 入口的审批人：访问令牌对应的操作者名。"""
    return os.environ.get("GENI_STUDIO_WEB_OPERATOR", "").strip() or "web"


def presented_token(request: Request) -> str:
    header = request.headers.get(HEADER, "").strip()
    if header:
        return header
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get(COOKIE, "").strip()


def token_matches(got: str) -> bool:
    expected = web_token()
    return bool(expected) and bool(got) and secrets.compare_digest(got, expected)


def needs_token(path: str) -> bool:
    return path.startswith("/api/") and not path.startswith("/api/webhooks/")


async def require_token(request: Request, call_next):
    if web_token() and needs_token(request.url.path) and not token_matches(presented_token(request)):
        return JSONResponse({"detail": "需要访问令牌。"}, status_code=401)
    return await call_next(request)


def is_loopback(host: str) -> bool:
    if host in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def check_listen_address(host: str) -> None:
    """监听非回环地址时必须设置访问令牌。"""
    if not is_loopback(host) and not web_token():
        raise SystemExit(f"监听 {host} 时必须设置 GENI_STUDIO_WEB_TOKEN。")
