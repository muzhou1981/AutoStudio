"""当前后端可选用的模型。列表来自 SDK，不在页面上手写模型名。"""

from __future__ import annotations

import os


def list_backend_models() -> dict:
    from geni_studio.backends.base import StubBackend, get_default_backend

    backend = get_default_backend()
    if isinstance(backend, StubBackend):
        return {"models": [], "source": "stub", "detail": ""}
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
