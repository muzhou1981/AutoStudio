"""当前后端可选用的模型。列表来自 SDK，不在页面上手写模型名。"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

from geni_studio.backends.reasoning import KNOWN_EFFORTS

# Cursor 各模型表达推理强度的参数名不统一，按此顺序取第一个出现的。
_CURSOR_EFFORT_PARAMS = ("effort", "reasoning_effort", "reasoning")
_CATALOG_TTL_SECONDS = 600
_cursor_catalog: dict[str, Any] = {"at": 0.0, "key": "", "rows": []}
_cursor_catalog_lock = threading.Lock()


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
    listed = None
    for attempt in range(2):
        try:
            listed = Cursor.models.list(api_key=api_key)
            break
        except Exception:  # noqa: BLE001 — SDK 失败只告诉页面读不到列表，不回显密钥
            if attempt == 0:
                continue
            return {
                "models": [],
                "source": "cursor",
                "detail": "读不到模型列表。请刷新配置页；若刚启动 Web，首次拉取有时会失败。",
            }
    if listed is None:
        return {"models": [], "source": "cursor", "detail": "读不到模型列表。"}
    models = [row for row in (cursor_model_row(item) for item in listed) if row]
    with _cursor_catalog_lock:
        _cursor_catalog.update(at=time.monotonic(), key=api_key, rows=models)
    return {"models": models, "source": "cursor", "detail": ""}


def cursor_model_row(item: Any) -> dict[str, Any] | None:
    """SDK 模型条目转为页面行；推理强度取自模型参数定义，默认值取自标记为默认的变体。"""
    model_id = str(getattr(item, "id", "") or "").strip()
    if not model_id:
        return None
    label = str(getattr(item, "display_name", "") or "").strip() or model_id
    row: dict[str, Any] = {"id": model_id, "label": label}
    params = {str(getattr(p, "id", "")): p for p in getattr(item, "parameters", ()) or ()}
    param_id = next((name for name in _CURSOR_EFFORT_PARAMS if name in params), "")
    if not param_id:
        return row
    efforts = [
        {"id": str(v.value), "label": str(getattr(v, "display_name", "") or v.value)}
        for v in params[param_id].values
        if str(v.value) in KNOWN_EFFORTS
    ]
    if not efforts:
        return row
    default = ""
    for variant in getattr(item, "variants", ()) or ():
        if getattr(variant, "is_default", False):
            default = next((str(p.value) for p in variant.params if p.id == param_id), "")
            break
    row.update(reasoning_param=param_id, reasoning_efforts=efforts, default_reasoning_effort=default)
    return row


def cursor_effort_param(model: str, effort: str) -> str:
    """Cursor 模型表示推理强度的参数名；模型不支持该强度时报错，不静默忽略。"""
    rows = _cursor_rows()
    if not rows:
        raise RuntimeError("读不到 Cursor 模型列表，无法设置推理强度。")
    row = next((item for item in rows if item["id"] == model), None)
    if row is None or not row.get("reasoning_param"):
        raise ValueError(f"Cursor 模型 {model} 不支持设置推理强度。")
    if effort not in {item["id"] for item in row["reasoning_efforts"]}:
        raise ValueError(f"Cursor 模型 {model} 不支持推理强度 {effort}。")
    return str(row["reasoning_param"])


def _cursor_rows() -> list[dict[str, Any]]:
    key = os.environ.get("CURSOR_API_KEY", "").strip()
    with _cursor_catalog_lock:
        fresh = _cursor_catalog["key"] == key and time.monotonic() - _cursor_catalog["at"] < _CATALOG_TTL_SECONDS
        if fresh and _cursor_catalog["rows"]:
            return list(_cursor_catalog["rows"])
    return _list_cursor_models()["models"]


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
