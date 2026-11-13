"""Cursor SDK 后端（Local Agent Run）。"""

from __future__ import annotations

import logging
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
    """同一（Run、角色、工作目录、模型、角色定义）复用一个 Cursor Agent，跨节点延续上下文。

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
        self._agent_run: dict[str, str] = {}
        # 每一轮一个桥接进程，环境里带本轮标识，这一轮派生的进程结束时可按标识回收。
        self._bridges: dict[str, tuple[object, object]] = {}
        self._role_sent: set[str] = set()
        self._lock = threading.Lock()
        # 只读并行支路共用工作目录，同一角色会落到同一 Agent，发送须串行。
        self._send_locks: dict[str, threading.Lock] = {}
        # 未指定默认模型时使用 SDK 的 Auto 路由（模型 ID 为 default）。
        from geni_studio.backends.base import factory_default_model

        self._model = factory_default_model("cursor") or "default"

    def _cwd(self) -> str:
        from geni_studio.workspace.context import current_worktree

        return current_worktree() or os.fspath(factory_root())

    def _agent_for_role(
        self, role_name: str, model: str, system_prompt: str = "", effort: str = "", fast: str = "",
        extra: dict[str, str] | None = None,
    ):
        from cursor_sdk.types import AgentOptions, LocalAgentOptions

        from geni_studio.backends.session import (
            load_session,
            save_session,
            session_digest,
            session_lock,
            session_path,
        )
        from geni_studio.hitl.control import current_thread_id

        cwd = self._cwd()
        run_id = current_thread_id() or ""
        identity = [run_id, role_name, cwd, model, system_prompt.strip()]
        if effort:
            # 显式强度不同的调用不共用 Agent；未设置时兼容已有会话键。
            identity.append(effort)
        if fast:
            identity.append(f"fast={fast}")
        if extra:
            identity.append(_params_text(extra).strip())
        key = session_digest(identity)
        with self._lock:
            agent = self._agents.get(key)
        if agent is not None:
            return key, agent
        # SDK 默认只加载内联 MCP；显式加载项目与用户层的 .cursor 配置（mcp.json、规则、Skill）。
        # 工作目录指向目标项目工作树，而不是工厂仓库。
        opts = AgentOptions(
            name=f"GeniStudio:{role_name}",
            local=LocalAgentOptions(cwd=cwd, setting_sources=SETTING_SOURCES),
            model=_model_selection(model, effort, fast, extra),
        )
        path = session_path("cursor-sessions", run_id, cwd, key) if run_id else None
        client = self._client_for(run_id)
        with session_lock(path):
            saved = load_session(path)
            agent_id = str(saved.get("agent_id") or "")
            if agent_id:
                # 恢复失败必须报错，不静默丢弃历史另开 Agent。
                agent = client.resume_agent(agent_id, opts)
                if saved.get("role_sent"):
                    self._mark_role_sent(key)
            else:
                agent = client.create_agent(opts, api_key=self._api_key)
                if path is not None:
                    save_session(path, {"agent_id": str(getattr(agent, "agent_id", "") or ""), "role_sent": False})
        with self._lock:
            self._agents[key] = agent
            self._agent_run[key] = run_id
        return key, agent

    def _client_for(self, run_id: str):
        if not run_id:
            return self._client
        with self._lock:
            pair = self._bridges.get(run_id)
            if pair is None:
                pair = _launch_run_bridge(run_id)
                if pair is None:
                    return self._client
                self._bridges[run_id] = pair
            return pair[1]

    def release_run(self, run_id: str) -> None:
        """关闭这一轮的 Agent 与桥接进程。会话标识仍在磁盘上，之后可以续接。"""
        with self._lock:
            keys = [key for key, owner in self._agent_run.items() if owner == run_id]
            agents = [self._agents.pop(key, None) for key in keys]
            for key in keys:
                self._agent_run.pop(key, None)
                self._role_sent.discard(key)
                self._send_locks.pop(key, None)
            pair = self._bridges.pop(run_id, None)
        for agent in agents:
            _quietly(getattr(agent, "close", None))
        if pair is not None:
            bridge, client = pair
            _quietly(getattr(client, "close", None))
            _quietly(getattr(bridge, "close", None))

    def close_all(self) -> None:
        with self._lock:
            runs = list(self._bridges)
        for run_id in runs:
            self.release_run(run_id)

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
        from geni_studio.backends.reasoning import fast_for_role, model_params_for_role
        from geni_studio.backends.runner import effort_for_role

        effort = effort_for_role(role_name)
        fast = fast_for_role(role_name)
        extra = model_params_for_role(role_name)
        key, agent = self._agent_for_role(role_name, model or self._model, system_prompt, effort, fast, extra)
        with self._lock:
            send_lock = self._send_locks.setdefault(key, threading.Lock())
        with send_lock:
            return self._send(key, agent, role_name, system_prompt, user_prompt, model, effort, fast, extra)

    def _send(
        self, key: str, agent: object, role_name: str, system_prompt: str,
        user_prompt: str, model: str | None, effort: str, fast: str = "",
        extra: dict[str, str] | None = None,
    ) -> str:
        from geni_studio.hitl.control import current_thread_id
        from geni_studio.hitl.conversation import (
            append_step,
            begin_turn,
            finish_turn,
            task_started_step,
        )
        from geni_studio.workspace.context import current_worktree

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

        def on_delta(update: object) -> None:
            if turn_path is None or getattr(update, "type", "") != "tool-call-started":
                return
            call = getattr(update, "tool_call", None)
            if isinstance(call, dict) and call.get("type") == "task":
                append_step(turn_path, task_started_step(call))

        from cursor_sdk.types import SendOptions

        run = agent.send(prompt, SendOptions(on_step=on_step, on_delta=on_delta))  # type: ignore[attr-defined]
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
                usage = getattr(getattr(run, "_terminal_result", None), "usage", None)
                finish_turn(turn_path, text, usage=None if usage is None else {
                    "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
                    "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
                })
        finally:
            if thread_id:
                unregister_active_run(thread_id, run)
        if thread_id and is_stop_requested(thread_id):
            raise RunStopped("本轮已停止")
        from geni_studio.backends.cost import note_cost

        usage = getattr(getattr(run, "_terminal_result", None), "usage", None)
        chosen = (
            (model or self._model) + (f" effort={effort}" if effort else "") + (f" fast={fast}" if fast else "")
            + _params_text(extra or {})
        )
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


log = logging.getLogger(__name__)

SETTING_SOURCES = ("project", "user")


def _launch_run_bridge(run_id: str) -> tuple[object, object] | None:
    from cursor_sdk._bridge import Bridge
    from cursor_sdk._client import Client
    from cursor_sdk._vendor import resolve_bridge_path

    from geni_studio.backends.run_processes import bridge_command

    bridge = Bridge.launch(bridge_command(run_id, resolve_bridge_path()), workspace=os.getcwd())
    return bridge, Client(bridge.endpoint, allow_api_key_env_fallback=True)


def _quietly(close) -> None:
    if not callable(close):
        return
    try:
        close()
    except Exception:
        log.debug("回收时关闭失败，桥接可能已退出", exc_info=True)


def _model_selection(model: str, effort: str, fast: str = "", extra: dict[str, str] | None = None):
    """未设任何模型参数时只传模型 ID；设置时按该模型的参数名组装 ModelSelection。"""
    extra = extra or {}
    if not effort and not fast and not extra:
        return model
    if model.strip().lower() in {"", "default", "auto"}:
        what = "推理强度" if effort else "Fast 模式" if fast else "上下文长度等模型参数"
        raise ValueError(f"Cursor 的 Auto 模型由服务端自动选择，不能指定{what}；请先为该角色选择具体模型。")
    from cursor_sdk.types import ModelParameterValue, ModelSelection

    from geni_studio.backends.models import cursor_selection_params

    params = cursor_selection_params(model, effort, fast, extra)
    return ModelSelection(id=model, params=tuple(ModelParameterValue(id=k, value=v) for k, v in params))


def _params_text(extra: dict[str, str]) -> str:
    return "".join(f" {name}={value}" for name, value in sorted(extra.items()))


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
