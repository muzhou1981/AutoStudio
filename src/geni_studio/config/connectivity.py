"""写入配置后的连通测试。不回显密钥，失败时也不删除已写入的值。"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def probe_saved_settings() -> dict[str, Any]:
    """按当前已生效的配置做探测。调用方应先完成写入。"""
    backend = os.environ.get("GENI_STUDIO_BACKEND", "").strip().lower()
    if backend not in {"stub", "cursor"}:
        backend = "cursor" if os.environ.get("CURSOR_API_KEY", "").strip() else "stub"
    model = os.environ.get("GENI_STUDIO_CURSOR_MODEL", "").strip()
    target = os.environ.get("GENI_STUDIO_TARGET_ROOT", "").strip()
    from geni_studio.hitl.feishu_config import resolve_lark_backend

    checks = [
        _check("默认工作区", *_workspace(target)),
        _check("Agent", *_agent(backend, model)),
        _check("飞书", *_feishu(resolve_lark_backend())),
    ]
    failed = [item for item in checks if item["status"] == "fail"]
    if failed:
        summary = "连不上。" + failed[0]["detail"]
        ok = False
    elif any(item["status"] == "ok" for item in checks):
        summary = "已连通。"
        ok = True
    else:
        summary = "未配置需要测试的凭证。"
        ok = True
    return {"ok": ok, "summary": summary, "checks": checks}


def _check(name: str, status: str, detail: str) -> dict[str, str]:
    return {"name": name, "status": status, "detail": detail}


def _workspace(path: str) -> tuple[str, str]:
    text = path.strip()
    if not text:
        return "skip", "未填写默认工作区，未检查。"
    folder = Path(text).expanduser()
    try:
        if folder.exists():
            if not folder.is_dir():
                return "fail", "默认工作区不是目录。换一个可写目录后再写入。"
            probe = folder / ".geni_studio_write_probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return "ok", "默认工作区可写。"
        parent = folder.parent
        if parent.is_dir() and os.access(parent, os.W_OK):
            return "ok", "默认工作区尚不存在，上级目录可写。"
    except OSError:
        return "fail", "默认工作区不可写。换一个可写目录后再写入。"
    return "fail", "默认工作区不可写。换一个可写目录后再写入。"


def _agent(backend: str, model: str) -> tuple[str, str]:
    if backend != "cursor":
        return "ok", "当前后端是 stub，不调用外部模型。"
    key = os.environ.get("CURSOR_API_KEY", "").strip()
    if not key:
        return "skip", "未配置 API Key，未测试。"
    return probe_cursor_key(key, model)


def probe_cursor_key(api_key: str, model: str) -> tuple[str, str]:
    """用 Cursor.me 核对密钥，不发起一轮生成。"""
    try:
        from cursor_sdk import Cursor
        from cursor_sdk._client import _default_client
        from cursor_sdk.errors import (
            AuthenticationError,
            ConfigurationError,
            CursorSDKError,
        )
    except ImportError:
        return "fail", "未安装 cursor-sdk。安装后再写入。"
    try:
        Cursor.me(client=_default_client(), api_key=api_key)
    except AuthenticationError:
        return "fail", "API Key 无效。到 Cursor 设置里更新 User API Key，再写入一次。"
    except ConfigurationError:
        return "fail", "Cursor 桥接未就绪。确认本机桥接可用后再写入。"
    except CursorSDKError:
        return "fail", "连不上 Cursor。检查网络或代理后再写入。"
    chosen = model.strip() or "Auto"
    return "ok", f"API Key 可用。运行时模型为 {chosen}。"


def _feishu(backend: str) -> tuple[str, str]:
    if backend == "lark_cli":
        from geni_studio.hitl.lark_cli_client import auth_summary

        summary = auth_summary()
        if summary.bot_ready:
            return "ok", "本机 lark-cli 可用。"
        hint = summary.hint or "本机 lark-cli 不可用。"
        return "fail", hint
    app_id = os.environ.get("LARK_APP_ID", "").strip()
    app_secret = os.environ.get("LARK_APP_SECRET", "").strip()
    if not app_id or not app_secret:
        return "skip", "未配置飞书应用凭据，未测试。"
    return probe_feishu_app(app_id, app_secret)


def probe_feishu_app(app_id: str, app_secret: str) -> tuple[str, str]:
    body = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode("utf-8")
    request = urllib.request.Request(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return "fail", "连不上飞书。检查网络后再写入。"
    if not isinstance(payload, dict):
        return "fail", "飞书没有返回可识别的结果。稍后再写入。"
    if int(payload.get("code") or 0) == 0 and payload.get("tenant_access_token"):
        return "ok", "飞书应用凭据可用。"
    return "fail", "飞书应用凭据对不上。核对 LARK_APP_ID 与 LARK_APP_SECRET 后再写入。"
