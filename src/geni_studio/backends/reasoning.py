"""角色推理强度：每个角色保存一个与后端无关的强度值，由各后端换成自己的请求参数。"""

from __future__ import annotations

import re
from contextlib import contextmanager
from contextvars import ContextVar

# Codex ReasoningEffort 枚举与 Cursor 模型参数取值的并集；具体模型是否支持由模型目录判定。
KNOWN_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh", "extra-high", "max", "ultra")
_role_efforts: ContextVar[dict[str, str] | None] = ContextVar("geni_role_efforts", default=None)


def normalize_effort(value: str | None) -> str:
    """空值、default、auto 表示交给模型默认，返回空串。"""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TypeError("reasoning_effort 必须是字符串")
    value = value.strip().lower()
    if value in {"", "default", "auto"}:
        return ""
    if value not in KNOWN_EFFORTS:
        raise ValueError("reasoning_effort 须为 default 或 " + ", ".join(KNOWN_EFFORTS))
    return value


def clean_role_reasoning_efforts(raw: dict[str, str] | None) -> dict[str, str]:
    result = {}
    for role, value in (raw or {}).items():
        role = role.strip()
        if not role or len(role) > 80:
            raise ValueError("角色标识不能为空或超过 80 个字符")
        if value is None or value == "":
            continue
        # 空字段继承项目/工厂；default 显式跳过它们，交给模型默认。
        result[role] = normalize_effort(value) or "default"
    return result


@contextmanager
def use_role_reasoning_efforts(values: dict[str, str] | None):
    token = _role_efforts.set(clean_role_reasoning_efforts(values))
    try:
        yield
    finally:
        _role_efforts.reset(token)


def reasoning_for_role(role: str, configured: str | None) -> str | None:
    return (_role_efforts.get() or {}).get(role, configured)


# Fast 模式：on/off 显式开关，未设置时交给模型默认（各模型默认值不同）。
FAST_MODES = ("on", "off")
_role_fast: ContextVar[dict[str, str] | None] = ContextVar("geni_role_fast_modes", default=None)


def normalize_fast(value: str | None) -> str:
    """空值、default 表示交给模型默认，返回空串。"""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TypeError("fast 必须是字符串")
    value = value.strip().lower()
    if value in {"", "default"}:
        return ""
    if value not in FAST_MODES:
        raise ValueError("fast 须为 default、on 或 off")
    return value


def clean_role_fast_modes(raw: dict[str, str] | None) -> dict[str, str]:
    result = {}
    for role, value in (raw or {}).items():
        role = role.strip()
        if not role or len(role) > 80:
            raise ValueError("角色标识不能为空或超过 80 个字符")
        mode = normalize_fast(value)
        if mode:
            result[role] = mode
    return result


@contextmanager
def use_role_fast_modes(values: dict[str, str] | None):
    token = _role_fast.set(clean_role_fast_modes(values))
    try:
        yield
    finally:
        _role_fast.reset(token)


def fast_for_role(role: str) -> str:
    """本轮该角色的 Fast 模式：on、off，或空串表示模型默认。"""
    return (_role_fast.get() or {}).get(role, "")


# 模型目录里推理强度与 Fast 之外、由运行页开放选择的参数；取值以目录声明为准。
MODEL_PARAMS = ("context",)
_PARAM_VALUE = re.compile(r"^[A-Za-z0-9._-]{1,40}$")
_role_params: ContextVar[dict[str, dict[str, str]] | None] = ContextVar("geni_role_model_params", default=None)


def clean_role_model_params(raw: dict[str, dict[str, str]] | None) -> dict[str, dict[str, str]]:
    """角色到“参数名 → 取值”；空值表示沿用模型默认，不写入。"""
    result: dict[str, dict[str, str]] = {}
    for role, params in (raw or {}).items():
        role = role.strip()
        if not role or len(role) > 80:
            raise ValueError("角色标识不能为空或超过 80 个字符")
        if params is None:
            continue
        if not isinstance(params, dict):
            raise TypeError("模型参数须为参数名到取值的映射")
        chosen = {}
        for name, value in params.items():
            if name not in MODEL_PARAMS:
                raise ValueError("模型参数只能是 " + ", ".join(MODEL_PARAMS))
            if value is None or value == "":
                continue
            if not isinstance(value, str) or not _PARAM_VALUE.match(value.strip()):
                raise ValueError(f"模型参数 {name} 的取值无效")
            chosen[name] = value.strip()
        if chosen:
            result[role] = chosen
    return result


@contextmanager
def use_role_model_params(values: dict[str, dict[str, str]] | None):
    token = _role_params.set(clean_role_model_params(values))
    try:
        yield
    finally:
        _role_params.reset(token)


def model_params_for_role(role: str) -> dict[str, str]:
    """本轮该角色显式选择的模型参数；未选的交给模型默认。"""
    return dict((_role_params.get() or {}).get(role, {}))
