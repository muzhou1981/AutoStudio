"""服务端用户配置：本服务使用者的偏好，Web 与 CLI 共用，换机器打开同一服务仍然生效。

包含两类：
- 角色模型参数记忆：推理强度、Fast 与开放的模型参数按“角色 → 后端:模型”保存，
  换模型时由界面恢复该模型上次的取值。只记有过选择的模型；某个模型全部沿用默认时删去该项。
- 界面偏好：目前只有主题。面板尺寸随屏幕而定，仍由各浏览器自己保存。
"""

from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path
from typing import Any

from geni_studio.backends.reasoning import (
    clean_role_fast_modes,
    clean_role_model_params,
    clean_role_reasoning_efforts,
)
from geni_studio.config.context import ConfigError, factory_root

_VERSION = 1
_BACKEND = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@:-]{0,119}$")
_lock = threading.Lock()
UI_PREFS: dict[str, tuple[str, ...]] = {"theme": ("light", "dark")}


def user_config_file() -> Path:
    """`GENI_STUDIO_USER_CONFIG_PATH` 优先；否则与检查点库同目录，预览实例因此与主服务隔离。"""
    raw = os.environ.get("GENI_STUDIO_USER_CONFIG_PATH", "").strip()
    if raw:
        return Path(raw).expanduser()
    from geni_studio.workspace.checkpoint import checkpoint_file

    checkpoint = checkpoint_file()
    folder = checkpoint.parent if checkpoint else factory_root() / "runs"
    return folder / "user_config.json"


def _read(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        raise ConfigError(f"用户配置无法读取：{path}（{exc}）") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"用户配置根节点须为对象：{path}")
    return data


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def model_key(backend: str, model: str) -> str:
    """记忆的键：后端与模型标识；模型为空表示该后端的默认模型（Cursor 为 Auto）。"""
    backend = (backend or "").strip()
    model = (model or "").strip() or "default"
    if not _BACKEND.match(backend):
        raise ValueError("后端标识无效")
    if not _MODEL.match(model):
        raise ValueError("模型标识无效")
    return backend + ":" + model


def clean_model_pref(role: str, entry: dict[str, Any] | None) -> dict[str, Any]:
    """一个模型的记忆：effort、fast、params；空值不写入。"""
    entry = entry or {}
    if not isinstance(entry, dict):
        raise TypeError("模型参数记忆须为对象")
    unknown = set(entry) - {"effort", "fast", "params"}
    if unknown:
        raise ValueError("模型参数记忆只能包含 effort、fast、params")
    result: dict[str, Any] = {}
    effort = clean_role_reasoning_efforts({role: entry.get("effort") or ""}).get(role.strip())
    if effort:
        result["effort"] = effort
    fast = clean_role_fast_modes({role: entry.get("fast") or ""}).get(role.strip())
    if fast:
        result["fast"] = fast
    params = clean_role_model_params({role: entry.get("params") or {}}).get(role.strip())
    if params:
        result["params"] = params
    return result


def _clean_prefs(raw: Any) -> dict[str, dict[str, dict[str, Any]]]:
    """丢弃文件中无法识别的条目，不让一处手改错误挡住整份记忆。"""
    result: dict[str, dict[str, dict[str, Any]]] = {}
    if not isinstance(raw, dict):
        return result
    for role, by_model in raw.items():
        if not isinstance(role, str) or not isinstance(by_model, dict):
            continue
        kept = {}
        for key, entry in by_model.items():
            backend, _, model = str(key).partition(":")
            try:
                if model_key(backend, model) != key:
                    continue
                cleaned = clean_model_pref(role, entry)
            except (TypeError, ValueError):
                continue
            if cleaned:
                kept[key] = cleaned
        if kept:
            result[role.strip()] = kept
    return result


def role_model_prefs() -> dict[str, dict[str, dict[str, Any]]]:
    """全部角色的模型参数记忆：角色 → 后端:模型 → {effort, fast, params}。"""
    with _lock:
        return _clean_prefs(_read(user_config_file()).get("role_model_prefs"))


def _clean_ui(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    return {name: value for name, value in raw.items() if name in UI_PREFS and value in UI_PREFS[name]}


def ui_prefs() -> dict[str, str]:
    """界面偏好：名称 → 取值；没设过的项不出现，由界面按系统设置决定。"""
    with _lock:
        return _clean_ui(_read(user_config_file()).get("ui"))


def set_ui_pref(name: str, value: str) -> dict[str, str]:
    """写入一项界面偏好；取值为空时删去，回到系统设置。返回写入后的全部界面偏好。"""
    name = (name or "").strip()
    value = (value or "").strip()
    if name not in UI_PREFS:
        raise ValueError("界面偏好只能是 " + ", ".join(UI_PREFS))
    if value and value not in UI_PREFS[name]:
        raise ValueError(f"界面偏好 {name} 须为 " + "、".join(UI_PREFS[name]))
    path = user_config_file()
    with _lock:
        data = _read(path)
        ui = _clean_ui(data.get("ui"))
        if value:
            ui[name] = value
        else:
            ui.pop(name, None)
        data["version"] = _VERSION
        data["ui"] = ui
        _write(path, data)
        return ui


def set_role_model_pref(role: str, backend: str, model: str, entry: dict[str, Any] | None) -> dict[str, Any]:
    """写入一个角色在一个模型上的记忆；entry 为空或全为默认时删去该项。返回写入后的全部记忆。"""
    role = (role or "").strip()
    key = model_key(backend, model)
    cleaned = clean_model_pref(role, entry)
    path = user_config_file()
    with _lock:
        data = _read(path)
        prefs = _clean_prefs(data.get("role_model_prefs"))
        by_model = prefs.setdefault(role, {})
        if cleaned:
            by_model[key] = cleaned
        else:
            by_model.pop(key, None)
        if not by_model:
            prefs.pop(role, None)
        data["version"] = _VERSION
        data["role_model_prefs"] = prefs
        _write(path, data)
        return prefs
