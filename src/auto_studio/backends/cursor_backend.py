"""Cursor SDK 后端（可选依赖 cursor-sdk）。"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from auto_studio.backends.base import AgentBackend


class CursorBackend:
    """连通性校验 + 占位补全；Agent Run 与图节点对接在 M2 后续迭代。"""

    def __init__(self) -> None:
        from cursor_sdk import Cursor  # type: ignore[import-untyped]

        api_key = os.environ.get("CURSOR_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("缺少 CURSOR_API_KEY")
        self._user = Cursor.me(api_key=api_key)

    def complete(
        self,
        *,
        role_name: str,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        _ = self._user
        return (
            f"[cursor-sdk:pending-run] role={role_name} "
            f"system_len={len(system_prompt)} user_len={len(user_prompt)}"
        )


def try_cursor_backend() -> AgentBackend | None:
    if os.environ.get("AUTO_STUDIO_BACKEND", "").strip().lower() != "cursor":
        return None
    try:
        return CursorBackend()
    except RuntimeError:
        return None
