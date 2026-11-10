"""当前后端可选用的模型。列表来自 SDK，不在页面上手写模型名。"""

from __future__ import annotations

import os


def _stub_models() -> dict:
    return {"models": [], "source": "stub", "detail": "stub 不调用外部模型。"}


def _list_cursor_models() -> dict:
    try:
        from cursor_sdk import Cursor
    except ImportError:
        return {"models": [], "source": "cursor", "detail": "读不到模型列表。"}
    api_key = os.environ.get("CURSOR_API_KEY", "").strip()
    if not api_key:
        return {"models": [], "source": "cursor", "detail": "读不到模型列表。先配置 Cursor API Key。"}
    try:
        listed = Cursor.models.list(api_key=api_key)
    except Exception:  # noqa: BLE001 — SDK 失败只告诉页面读不到列表，不回显密钥
        return {"models": [], "source": "cursor", "detail": "读不到模型列表。"}
    models = []
    for item in listed:
        model_id = str(getattr(item, "id", "") or "").strip()
        if not model_id:
            continue
        label = str(getattr(item, "display_name", "") or "").strip() or model_id
        models.append({"id": model_id, "label": label})
    return {"models": models, "source": "cursor", "detail": ""}


def list_backend_models(*, backend: str | None = None) -> dict:
    """按指定或当前生效后端列出模型。配置页可传 backend=cursor 且尚未写入 .env。"""
    mode = (backend or os.environ.get("GENI_STUDIO_BACKEND", "")).strip().lower()
    if not mode:
        mode = "cursor"
    if mode == "stub":
        return _stub_models()
    if mode == "codex":
        from geni_studio.backends.codex_backend import list_codex_models

        return list_codex_models()
    if mode == "cursor":
        return _list_cursor_models()
    return {"models": [], "source": mode, "detail": "未知 Agent 后端。"}
