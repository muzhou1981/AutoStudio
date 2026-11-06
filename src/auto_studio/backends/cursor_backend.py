"""Cursor SDK 后端（Local Agent Run）。"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from auto_studio.config.context import factory_root

if TYPE_CHECKING:
    from auto_studio.backends.base import AgentBackend


def ensure_lowercase_proxy() -> None:
    """Node 桥接读取小写代理变量，并用 NODE_USE_ENV_PROXY 让 fetch 走代理。"""
    saw_proxy = False
    for upper, lower in (
        ("HTTP_PROXY", "http_proxy"),
        ("HTTPS_PROXY", "https_proxy"),
        ("NO_PROXY", "no_proxy"),
    ):
        if os.environ.get(upper) and not os.environ.get(lower):
            os.environ[lower] = os.environ[upper]
        if os.environ.get(upper) or os.environ.get(lower):
            saw_proxy = True
    if saw_proxy and not os.environ.get("NODE_USE_ENV_PROXY"):
        os.environ["NODE_USE_ENV_PROXY"] = "1"


class CursorBackend:
    capabilities: frozenset[str] = frozenset({"text", "file_read", "file_write", "shell", "mcp"})

    def __init__(self) -> None:
        ensure_lowercase_proxy()
        from cursor_sdk._client import _default_client

        api_key = os.environ.get("CURSOR_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("缺少 CURSOR_API_KEY")
        self._api_key = api_key
        self._client = _default_client()
        self._agents: dict[tuple[str, str], object] = {}
        # 需求 7：未显式指定时使用 SDK 的 Auto 路由（模型 ID 为 default）。
        self._model = os.environ.get("AUTO_STUDIO_CURSOR_MODEL", "").strip() or "default"

    def _cwd(self) -> str:
        from auto_studio.workspace.context import current_worktree

        return current_worktree() or os.fspath(factory_root())

    def _agent_for_role(self, role_name: str, model: str):
        from cursor_sdk.types import AgentOptions, LocalAgentOptions

        cwd = self._cwd()
        key = (role_name, cwd, model)
        if key not in self._agents:
            # tools 保持 SDK 默认，以便复用 Cursor 已有的 MCP、规则与 Skill。
            # 工作目录指向目标项目工作树，而不是工厂仓库。
            opts = AgentOptions(
                name=f"auto_studio:{role_name}",
                local=LocalAgentOptions(cwd=cwd),
                model=model,
            )
            self._agents[key] = self._client.create_agent(
                opts,
                api_key=self._api_key,
            )
        return self._agents[key]

    def complete(
        self,
        *,
        role_name: str,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
    ) -> str:
        agent = self._agent_for_role(role_name, model or self._model)
        prompt = (
            f"{system_prompt.strip()}\n\n---\n\n"
            f"## 本轮任务\n\n{user_prompt.strip()}"
        )
        run = agent.send(prompt)  # type: ignore[attr-defined]
        from auto_studio.hitl.control import (
            RunStopped,
            current_thread_id,
            is_stop_requested,
            register_active_run,
            unregister_active_run,
        )

        thread_id = current_thread_id()
        if thread_id:
            register_active_run(thread_id, run)
        try:
            if thread_id and is_stop_requested(thread_id):
                run.cancel()
                raise RunStopped("本轮已停止")
            text = run.text().strip()
        finally:
            if thread_id:
                unregister_active_run(thread_id, run)
        if thread_id and is_stop_requested(thread_id):
            raise RunStopped("本轮已停止")
        from auto_studio.hitl.control import RunPaused, is_pause_requested

        if thread_id and is_pause_requested(thread_id):
            raise RunPaused("本轮已暂停")
        from auto_studio.backends.cost import note_cost

        usage = getattr(getattr(run, "_terminal_result", None), "usage", None)
        if usage is None:
            note_cost(f"role={role_name} backend=cursor model={model or self._model} usage=unknown")
        else:
            note_cost(
                "role="
                f"{role_name} backend=cursor model={model or self._model} "
                f"input_tokens={getattr(usage, 'input_tokens', 0)} "
                f"output_tokens={getattr(usage, 'output_tokens', 0)}"
            )
        return text


def _cursor_backend_enabled() -> bool:
    mode = os.environ.get("AUTO_STUDIO_BACKEND", "").strip().lower()
    if mode == "stub":
        return False
    if mode == "cursor":
        return True
    # 需求默认 Cursor SDK：已配置 CURSOR_API_KEY 时自动启用
    return bool(os.environ.get("CURSOR_API_KEY", "").strip())


def try_cursor_backend() -> AgentBackend | None:
    if not _cursor_backend_enabled():
        return None
    bridge_errors: tuple[type[BaseException], ...] = (RuntimeError, OSError)
    try:
        from cursor_sdk.errors import ConfigurationError

        bridge_errors = (RuntimeError, OSError, ConfigurationError)
    except ImportError:
        pass
    try:
        backend = CursorBackend()
    except bridge_errors:
        return None
    except ImportError:
        return None
    if os.environ.get("AUTO_STUDIO_CURSOR_VERIFY", "1").strip().lower() in (
        "0",
        "false",
        "no",
    ):
        return backend
    try:
        from cursor_sdk import Cursor
        from cursor_sdk.errors import AuthenticationError, CursorSDKError

        Cursor.me(client=backend._client, api_key=backend._api_key)
    except AuthenticationError:
        return None
    except CursorSDKError:
        return backend
    except ImportError:
        return backend
    return backend
