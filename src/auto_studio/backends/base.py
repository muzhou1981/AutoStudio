"""Agent 后端抽象（M2：Cursor SDK 等）。"""

from __future__ import annotations

from typing import Protocol


class AgentBackend(Protocol):
    """单次角色调用：读 role 定义 + 上下文，返回模型输出文本。"""

    def complete(
        self,
        *,
        role_name: str,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        """执行一次补全；失败应抛出 RuntimeError。"""


class StubBackend:
    """占位后端，保持图可跑通。"""

    def complete(
        self,
        *,
        role_name: str,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        return f"[stub:{role_name}] len={len(user_prompt)}"


def get_default_backend() -> AgentBackend:
    from auto_studio.backends.cursor_backend import try_cursor_backend

    return try_cursor_backend() or StubBackend()
