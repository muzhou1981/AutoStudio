"""Agent 后端抽象（M2：Cursor SDK 等）。"""

from __future__ import annotations

from typing import Protocol


class AgentBackend(Protocol):
    """单次角色调用：读 role 定义 + 上下文，返回模型输出文本。"""

    capabilities: frozenset[str]

    def complete(
        self,
        *,
        role_name: str,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
    ) -> str:
        """执行一次补全；失败应抛出 RuntimeError。"""


class StubBackend:
    """占位后端，保持图可跑通。不具备文件与命令能力。"""

    capabilities: frozenset[str] = frozenset({"text"})

    def complete(
        self,
        *,
        role_name: str,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
    ) -> str:
        return f"[stub:{role_name}] len={len(user_prompt)}"


def factory_default_model(backend: str = "") -> str:
    """配置页的默认模型。角色在某一轮没有另选时使用。"""
    import os

    from geni_studio.backends.runtime import current_config

    frozen = current_config()
    if frozen is not None:
        return str((frozen.get("_models") or {}).get(backend or frozen.get("_backend")) or "")
    current = os.environ.get("GENI_STUDIO_BACKEND", "").strip().lower() or "cursor"
    mode = backend or current
    specific = os.environ.get(f"GENI_STUDIO_{mode.upper()}_MODEL", "").strip()
    if specific:
        return specific
    return os.environ.get("GENI_STUDIO_DEFAULT_MODEL", "").strip() if mode == current else ""


def get_default_backend() -> AgentBackend:
    import os

    mode = os.environ.get("GENI_STUDIO_BACKEND", "").strip().lower() or "cursor"
    if mode == "stub":
        return StubBackend()
    if mode == "codex":
        from geni_studio.backends.codex_backend import try_codex_backend

        backend = try_codex_backend()
        if backend is None:
            raise RuntimeError("Codex 后端不可用，请安装 openai-codex")
        return backend
    if mode != "cursor":
        raise ValueError(f"未知 Agent 后端：{mode}")
    from geni_studio.backends.cursor_backend import try_cursor_backend

    backend = try_cursor_backend()
    if backend is None:
        raise RuntimeError("Cursor 后端不可用，请检查 SDK、凭证与桥接；演示需显式选择 stub")
    return backend
