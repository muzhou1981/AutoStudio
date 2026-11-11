"""Cursor SDK 后端（Local Agent Run）。"""

from __future__ import annotations

import os
import threading
from typing import TYPE_CHECKING

from geni_studio.config.context import factory_root

if TYPE_CHECKING:
    from geni_studio.backends.base import AgentBackend


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
    """同一（Run、节点、角色、工作目录、模型、角色定义）复用一个 Cursor Agent。

    Agent 标识落盘到运行目录 `cursor-sessions/`，进程重启或新实例可用 `resume_agent` 续接；
    角色定义只在 Agent 的首条消息中发送一次。
    """

    capabilities: frozenset[str] = frozenset({"read_files", "write_files", "run_commands", "mcp"})

    def __init__(self) -> None:
        ensure_lowercase_proxy()
        from cursor_sdk._client import _default_client

        api_key = os.environ.get("CURSOR_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("缺少 CURSOR_API_KEY")
        self._api_key = api_key
        self._client = _default_client()
        self._agents: dict[str, object] = {}
        self._role_sent: set[str] = set()
        self._lock = threading.Lock()
        # 未指定默认模型时使用 SDK 的 Auto 路由（模型 ID 为 default）。
        from geni_studio.backends.base import factory_default_model

        self._model = factory_default_model("cursor") or "default"

    def _cwd(self) -> str:
        from geni_studio.workspace.context import current_worktree

        return current_worktree() or os.fspath(factory_root())

    def _agent_for_role(self, role_name: str, model: str, system_prompt: str = "", effort: str = ""):
        from cursor_sdk.types import AgentOptions, LocalAgentOptions

        from geni_studio.backends.session import (
            current_node_id,
            load_session,
            save_session,
            session_digest,
            session_lock,
            session_path,
        )
        from geni_studio.hitl.control import current_thread_id

        cwd = self._cwd()
        run_id = current_thread_id() or ""
        identity = [run_id, current_node_id(), role_name, cwd, model, system_prompt.strip()]
        if effort:
            # 显式强度不同的调用不共用 Agent；未设置时兼容已有会话键。
            identity.append(effort)
        key = session_digest(identity)
        with self._lock:
            agent = self._agents.get(key)
        if agent is not None:
            return key, agent
        # tools 保持 SDK 默认，以便复用 Cursor 已有的 MCP、规则与 Skill。
        # 工作目录指向目标项目工作树，而不是工厂仓库。
        opts = AgentOptions(
            name=f"GeniStudio:{role_name}",
            local=LocalAgentOptions(cwd=cwd),
            model=_model_selection(model, effort),
        )
        path = session_path("cursor-sessions", run_id, cwd, key) if run_id else None
        with session_lock(path):
            saved = load_session(path)
            agent_id = str(saved.get("agent_id") or "")
            if agent_id:
                # 恢复失败必须报错，不静默丢弃历史另开 Agent。
                agent = self._client.resume_agent(agent_id, opts)
                if saved.get("role_sent"):
                    self._mark_role_sent(key)
            else:
                agent = self._client.create_agent(opts, api_key=self._api_key)
                if path is not None:
                    save_session(path, {"agent_id": str(getattr(agent, "agent_id", "") or ""), "role_sent": False})
        with self._lock:
            self._agents[key] = agent
        return key, agent

    def _mark_role_sent(self, key: str) -> None:
        from geni_studio.backends.session import (
            load_session,
            save_session,
            session_path,
        )
        from geni_studio.hitl.control import current_thread_id

        if key in self._role_sent:
            return
        self._role_sent.add(key)
        run_id = current_thread_id()
        if not run_id:
            return
        path = session_path("cursor-sessions", run_id, self._cwd(), key)
        saved = load_session(path)
        if saved.get("agent_id"):
            save_session(path, {**saved, "role_sent": True})

    def _message(self, key: str, system_prompt: str, user_prompt: str) -> str:
        task = f"## 本轮任务\n\n{user_prompt.strip()}"
        if key in self._role_sent:
            return task
        return f"{system_prompt.strip()}\n\n---\n\n{task}"

    def complete(
        self,
        *,
        role_name: str,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
    ) -> str:
        from geni_studio.backends.runner import effort_for_role
        from geni_studio.hitl.control import current_thread_id
        from geni_studio.hitl.conversation import append_step, begin_turn, finish_turn
        from geni_studio.workspace.context import current_worktree

        effort = effort_for_role(role_name)
        key, agent = self._agent_for_role(role_name, model or self._model, system_prompt, effort)
        prompt = self._message(key, system_prompt, user_prompt)
        thread_id = current_thread_id()
        turn_path = None
        if thread_id:
            turn_path = begin_turn(
                thread_id,
                role_name,
                agent_id=str(getattr(agent, "agent_id", "") or ""),
                model=model or self._model,
                prompt=prompt,
                workspace_path=current_worktree(),
            )

        def on_step(step: object) -> None:
            if turn_path is not None:
                append_step(turn_path, step)

        from cursor_sdk.types import SendOptions

        run = agent.send(prompt, SendOptions(on_step=on_step))  # type: ignore[attr-defined]
        from geni_studio.hitl.control import (
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
            self._mark_role_sent(key)
            if turn_path is not None:
                finish_turn(turn_path, text)
        finally:
            if thread_id:
                unregister_active_run(thread_id, run)
        if thread_id and is_stop_requested(thread_id):
            raise RunStopped("本轮已停止")
        from geni_studio.backends.cost import note_cost

        usage = getattr(getattr(run, "_terminal_result", None), "usage", None)
        chosen = (model or self._model) + (f" effort={effort}" if effort else "")
        if usage is None:
            note_cost(f"role={role_name} backend=cursor model={chosen} usage=unknown")
        else:
            note_cost(
                "role="
                f"{role_name} backend=cursor model={chosen} "
                f"input_tokens={getattr(usage, 'input_tokens', 0)} "
                f"output_tokens={getattr(usage, 'output_tokens', 0)}"
            )
        return text


def _model_selection(model: str, effort: str):
    """未设推理强度时只传模型 ID；设置时按该模型的参数名组装 ModelSelection。"""
    if not effort:
        return model
    if model.strip().lower() in {"", "default", "auto"}:
        raise ValueError("Cursor 的 Auto 模型由服务端自动选择，不能指定推理强度；请先为该角色选择具体模型。")
    from cursor_sdk.types import ModelParameterValue, ModelSelection

    from geni_studio.backends.models import cursor_effort_param

    param = cursor_effort_param(model, effort)
    return ModelSelection(id=model, params=(ModelParameterValue(id=param, value=effort),))


def _cursor_backend_enabled() -> bool:
    mode = os.environ.get("GENI_STUDIO_BACKEND", "").strip().lower()
    if mode in {"stub", "codex"}:
        return False
    if mode == "cursor":
        return True
    # 需求默认 Cursor SDK：已配置 CURSOR_API_KEY 时自动启用
    return bool(os.environ.get("CURSOR_API_KEY", "").strip())


_cache_lock = threading.Lock()
_cached: dict[tuple[str, bool], AgentBackend] = {}


def reset_cursor_backend_cache() -> None:
    with _cache_lock:
        _cached.clear()


def try_cursor_backend(*, force: bool = False) -> AgentBackend | None:
    """进程内复用同一个 Cursor 后端；连通性只在首次创建时校验，失败不缓存。"""
    if not force and not _cursor_backend_enabled():
        return None
    verify = os.environ.get("GENI_STUDIO_CURSOR_VERIFY", "1").strip().lower() not in ("0", "false", "no")
    key = (os.environ.get("CURSOR_API_KEY", "").strip(), verify)
    with _cache_lock:
        cached = _cached.get(key)
        if cached is not None:
            return cached
        backend = _create_cursor_backend(verify)
        if backend is not None:
            _cached[key] = backend
        return backend


def _create_cursor_backend(verify: bool) -> AgentBackend | None:
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
    if not verify:
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
