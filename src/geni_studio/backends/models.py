"""当前后端可选用的模型。列表来自 SDK，不在页面上手写模型名。"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

from geni_studio.backends.reasoning import KNOWN_EFFORTS, MODEL_PARAMS

# Cursor 各模型表达推理强度的参数名不统一，按此顺序取第一个出现的。
_CURSOR_EFFORT_PARAMS = ("effort", "reasoning_effort", "reasoning")
_CURSOR_FAST_PARAM = "fast"
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
    defaults: dict[str, str] = {}
    for variant in getattr(item, "variants", ()) or ():
        if getattr(variant, "is_default", False):
            defaults = {str(p.id): str(p.value) for p in variant.params}
            break
    fast = params.get(_CURSOR_FAST_PARAM)
    if fast is not None and {str(v.value) for v in fast.values} >= {"true", "false"}:
        row.update(fast=True, default_fast={"true": "on", "false": "off"}.get(defaults.get(_CURSOR_FAST_PARAM, ""), ""))
    extra = [
        {
            "id": name,
            "values": [
                {"id": str(v.value), "label": str(getattr(v, "display_name", "") or v.value)}
                for v in params[name].values
            ],
            "default": defaults.get(name, ""),
        }
        for name in MODEL_PARAMS
        if name in params and params[name].values
    ]
    if extra:
        row["params"] = extra
    param_id = next((name for name in _CURSOR_EFFORT_PARAMS if name in params), "")
    efforts = [
        {"id": str(v.value), "label": str(getattr(v, "display_name", "") or v.value)}
        for v in (params[param_id].values if param_id else ())
        if str(v.value) in KNOWN_EFFORTS
    ]
    if efforts:
        row.update(
            reasoning_param=param_id, reasoning_efforts=efforts,
            default_reasoning_effort=defaults.get(param_id, ""),
        )
    combos = _selectable_variants(item, row)
    if combos:
        row["variants"] = combos
    return row


def _selectable_variants(item: Any, row: dict[str, Any]) -> list[dict[str, str]]:
    """目录允许的组合，只保留页面可选的参数。

    全组合都允许，或变体没有逐项列出这些参数（无从判断）时返回空，不做组合校验。
    """
    names = {str(p["id"]) for p in row.get("params", ())}
    if row.get("reasoning_param"):
        names.add(str(row["reasoning_param"]))
    if row.get("fast"):
        names.add(_CURSOR_FAST_PARAM)
    if not names:
        return []
    seen: list[dict[str, str]] = []
    for variant in getattr(item, "variants", ()) or ():
        combo = {str(p.id): str(p.value) for p in variant.params if str(p.id) in names}
        if set(combo) != names:
            return []
        if combo not in seen:
            seen.append(combo)
    full = 1
    for param in getattr(item, "parameters", ()) or ():
        if str(getattr(param, "id", "")) in names:
            full *= max(len(param.values), 1)
    return seen if len(seen) < full else []


def cursor_selection_params(model: str, effort: str, fast: str, extra: dict[str, str]) -> list[tuple[str, str]]:
    """把本轮选择换成 Cursor 模型参数；参数未声明、取值不支持或组合不在目录中时报错。"""
    rows = _cursor_rows()
    if not rows:
        raise RuntimeError("读不到 Cursor 模型列表，无法设置模型参数。")
    row = next((item for item in rows if item["id"] == model), None)
    if row is None:
        raise ValueError(f"Cursor 模型 {model} 不在模型目录中。")
    chosen: list[tuple[str, str]] = []
    if effort:
        chosen.append((cursor_effort_param(model, effort), effort))
    if fast:
        cursor_fast_supported(model)
        chosen.append((_CURSOR_FAST_PARAM, "true" if fast == "on" else "false"))
    declared = {str(p["id"]): p for p in row.get("params", ())}
    for name, value in sorted(extra.items()):
        param = declared.get(name)
        if param is None:
            raise ValueError(f"Cursor 模型 {model} 没有参数 {name}。")
        if value not in {str(v["id"]) for v in param["values"]}:
            raise ValueError(f"Cursor 模型 {model} 的参数 {name} 不支持取值 {value}。")
        chosen.append((name, value))
    combos = row.get("variants") or []
    if not combos:
        return chosen
    picked = dict(chosen)
    fits = [combo for combo in combos if all(combo.get(k) == v for k, v in picked.items())]
    if not fits:
        text = "、".join(f"{k}={v}" for k, v in chosen)
        raise ValueError(f"Cursor 模型 {model} 不支持这组参数：{text}。")
    defaults = _default_combo(row)
    if not any(all(combo.get(k) == v for k, v in {**defaults, **picked}.items()) for combo in fits):
        # 未选的项由服务端按默认补齐会落到目录外的组合，改为显式传离默认最近的允许组合。
        best = max(fits, key=lambda combo: sum(combo.get(k) == v for k, v in defaults.items()))
        chosen += [(k, best[k]) for k in sorted(best) if k not in picked and best[k] != defaults.get(k)]
    return chosen


def _default_combo(row: dict[str, Any]) -> dict[str, str]:
    combo = {str(p["id"]): str(p["default"]) for p in row.get("params", ()) if p.get("default")}
    if row.get("reasoning_param") and row.get("default_reasoning_effort"):
        combo[str(row["reasoning_param"])] = str(row["default_reasoning_effort"])
    if row.get("default_fast"):
        combo[_CURSOR_FAST_PARAM] = "true" if row["default_fast"] == "on" else "false"
    return combo


def cursor_fast_supported(model: str) -> None:
    """模型不支持 Fast 模式时报错，不静默忽略。"""
    rows = _cursor_rows()
    if not rows:
        raise RuntimeError("读不到 Cursor 模型列表，无法设置 Fast 模式。")
    row = next((item for item in rows if item["id"] == model), None)
    if row is None or not row.get("fast"):
        raise ValueError(f"Cursor 模型 {model} 不支持 Fast 模式。")


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


def _cached_cursor_rows() -> list[dict[str, Any]]:
    key = os.environ.get("CURSOR_API_KEY", "").strip()
    with _cursor_catalog_lock:
        fresh = _cursor_catalog["key"] == key and time.monotonic() - _cursor_catalog["at"] < _CATALOG_TTL_SECONDS
        return list(_cursor_catalog["rows"]) if fresh else []


def _cursor_rows() -> list[dict[str, Any]]:
    return _cached_cursor_rows() or _list_cursor_models()["models"]


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
        cached = _cached_cursor_rows()
        if cached:
            return {"models": cached, "source": "cursor", "detail": ""}
        return _list_cursor_models()
    return {"models": [], "source": mode, "detail": "未知 Agent 后端。"}
