"""角色推理强度：每个角色保存一个与后端无关的强度值，由各后端换成自己的请求参数。"""

from __future__ import annotations

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
