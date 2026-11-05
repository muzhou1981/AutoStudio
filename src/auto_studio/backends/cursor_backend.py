"""Cursor SDK 后端（Local Agent Run）。"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from auto_studio.config.context import factory_root

if TYPE_CHECKING:
    from auto_studio.backends.base import AgentBackend


class CursorBackend:
    def __init__(self) -> None:
        from cursor_sdk import Client
        from cursor_sdk.types import LocalAgentOptions

        api_key = os.environ.get("CURSOR_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("缺少 CURSOR_API_KEY")
        self._api_key = api_key
        self._client = Client()
        self._local = LocalAgentOptions(cwd=os.fspath(factory_root()))
        self._agents: dict[str, object] = {}

    def _agent_for_role(self, role_name: str):
        from cursor_sdk.types import AgentOptions

        if role_name not in self._agents:
            opts = AgentOptions(
                name=f"auto_studio:{role_name}",
                local=self._local,
            )
            self._agents[role_name] = self._client.create_agent(
                opts,
                api_key=self._api_key,
            )
        return self._agents[role_name]

    def complete(
        self,
        *,
        role_name: str,
        system_prompt: str,
        user_prompt: str,
    ) -> str:
        agent = self._agent_for_role(role_name)
        prompt = (
            f"{system_prompt.strip()}\n\n---\n\n"
            f"## 本轮任务\n\n{user_prompt.strip()}"
        )
        run = agent.send(prompt)  # type: ignore[attr-defined]
        return run.text().strip()


def try_cursor_backend() -> AgentBackend | None:
    if os.environ.get("AUTO_STUDIO_BACKEND", "").strip().lower() != "cursor":
        return None
    try:
        return CursorBackend()
    except RuntimeError:
        return None
