"""Codex SDK 后端：有界调用、按 Run/节点隔离并持久化线程。"""

from __future__ import annotations

import hashlib
import json
import math
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from geni_studio.backends.base import AgentBackend


@contextmanager
def _open_codex(*, timeout: float = 30):
    from openai_codex import Codex

    # SDK 构造过程自行启动并初始化 app-server；构造失败由 SDK 关闭进程。
    client = Codex()
    expired = threading.Event()

    def expire():
        expired.set()
        client.close()

    timer = threading.Timer(timeout, expire)
    timer.daemon = True
    timer.start()
    try:
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        if key:
            client.login_api_key(key)
        yield client
        if expired.is_set():
            raise TimeoutError("Codex 调用超时")
    except Exception as exc:
        if expired.is_set():
            raise TimeoutError("Codex 调用超时") from exc
        raise
    finally:
        timer.cancel()
        client.close()


class _ActiveTurn:
    def __init__(self, handle: Any, client: Any):
        self.handle = handle
        self.client = client

    def cancel(self):
        # interrupt 的 RPC 也可能阻塞；短暂等待后关闭客户端以解除 stream 等待。
        worker = threading.Thread(target=_interrupt, args=(self.handle,), daemon=True)
        worker.start()
        worker.join(timeout=0.5)
        self.client.close()


class CodexBackend:
    capabilities: frozenset[str] = frozenset({"text", "file_read", "file_write", "shell"})

    def __init__(self, *, sandbox: str = "", timeout_seconds: float = 1800) -> None:
        if sandbox not in {"", "read-only", "workspace-write"}:
            raise ValueError("Codex sandbox 只支持 read-only 或 workspace-write")
        timeout = float(timeout_seconds)
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Codex timeout_seconds 必须是有限正数")
        self._sandbox = sandbox
        self._timeout = timeout
        # 未绑定 Run 的直接调用也能在同一对象内续接，但不跨对象共享。
        self._threads: dict[str, str] = {}

    def complete(
        self,
        *,
        role_name: str,
        system_prompt: str,
        user_prompt: str,
        model: str | None = None,
    ) -> str:
        from openai_codex import ApprovalMode, Sandbox

        from geni_studio.backends.base import factory_default_model
        from geni_studio.backends.cost import note_cost
        from geni_studio.backends.runner import required_capabilities
        from geni_studio.hitl.control import (
            RunStopped,
            current_thread_id,
            is_stop_requested,
            register_active_run,
            unregister_active_run,
        )
        from geni_studio.hitl.conversation import begin_turn, finish_turn
        from geni_studio.workspace.context import current_worktree

        cwd = current_worktree()
        if not cwd or not Path(cwd).is_dir():
            raise RuntimeError("Codex 需要有效的本轮工作区，请启用 GENI_STUDIO_WORKSPACE")
        cwd = str(Path(cwd).resolve())
        if is_stop_requested():
            raise RunStopped("本轮已停止")
        needs_write = role_name in {"developer", "tester"} or "file_write" in required_capabilities(role_name)
        sandbox = self._sandbox or ("workspace-write" if needs_write else "read-only")
        if needs_write and sandbox == "read-only":
            raise ValueError(f"{role_name} 需要写工作区，不能使用 read-only")
        chosen = _codex_model(model if model is not None else factory_default_model("codex"))
        run_id = current_thread_id()
        identity = [run_id, _node_id(), role_name, cwd, chosen, sandbox, system_prompt.strip()]
        digest = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()
        session_path = _session_path(run_id, cwd, digest) if run_id else None
        options = {
            "cwd": cwd,
            "sandbox": Sandbox(sandbox),
            "approval_mode": ApprovalMode.deny_all,
            "developer_instructions": system_prompt.strip(),
        }
        if chosen:
            options["model"] = chosen
        turn_path = None
        try:
            with _session_lock(session_path), _open_codex(timeout=self._timeout) as client:
                saved = self._threads.get(digest)
                if session_path is not None and session_path.exists():
                    saved = json.loads(session_path.read_text(encoding="utf-8"))["thread_id"]
                if saved:
                    # 恢复失败必须报错，不静默丢弃历史重开线程。
                    thread = client.thread_resume(saved, **options)
                else:
                    thread = client.thread_start(**options)
                self._threads[digest] = thread.id
                if session_path is not None:
                    _save_session(session_path, thread.id)
                if run_id:
                    turn_path = begin_turn(
                        run_id, role_name, agent_id=thread.id, model=chosen or "default",
                        prompt=user_prompt.strip(), workspace_path=cwd,
                    )
                handle = thread.turn(user_prompt.strip())
                active = _ActiveTurn(handle, client)
                register_active_run(run_id, active)
                try:
                    if is_stop_requested():
                        active.cancel()
                        raise RunStopped("本轮已停止")
                    text, usage = _consume_turn(handle, turn_path)
                finally:
                    unregister_active_run(run_id, active)
            if is_stop_requested():
                raise RunStopped("本轮已停止")
            if turn_path is not None:
                finish_turn(turn_path, text)
            note_cost(_cost_line(role_name, chosen, usage))
            return text
        except Exception as exc:
            if turn_path is not None:
                from geni_studio.hitl.conversation import append_step

                # 异常文本可能含 SDK 网络/认证细节，只记录异常类型。
                append_step(turn_path, {"type": "error", "message": type(exc).__name__})
            if is_stop_requested():
                raise RunStopped("本轮已停止") from exc
            raise


def _node_id() -> str:
    from langgraph.config import get_config

    try:
        return str((get_config().get("metadata") or {}).get("langgraph_node") or "")
    except RuntimeError:
        return ""


def _session_path(run_id: str, cwd: str, digest: str) -> Path:
    from geni_studio.hitl.conversation import conversation_dir

    return conversation_dir(run_id, cwd).parent / "codex-sessions" / f"{digest}.json"


@contextmanager
def _session_lock(path: Path | None):
    import fcntl

    if path is None:
        yield
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _save_session(path: Path, thread_id: str) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"thread_id": thread_id}), encoding="utf-8")
    temporary.replace(path)


def _consume_turn(handle: Any, turn_path: Path | None) -> tuple[str, Any]:
    from geni_studio.hitl.conversation import append_step

    final = ""
    unphased = ""
    terminal = None
    usage = None
    stream = handle.stream()
    try:
        for event in stream:
            data = event.payload.model_dump(mode="json", by_alias=True)
            if turn_path is not None:
                append_step(turn_path, {"type": event.method, "message": data})
            if event.method == "turn/completed":
                turn = data["turn"]
                if turn["id"] == handle.id:
                    terminal = turn
            elif data.get("turnId") == handle.id:
                if event.method == "item/completed":
                    item = data["item"]
                    if item.get("type") == "agentMessage":
                        if item.get("phase") == "final_answer":
                            final = item.get("text") or ""
                        elif item.get("phase") is None:
                            unphased = item.get("text") or ""
                elif event.method == "thread/tokenUsage/updated":
                    usage = data.get("tokenUsage")
    finally:
        stream.close()
    if terminal is None or terminal.get("status") != "completed" or terminal.get("error") is not None:
        raise RuntimeError("Codex 本轮没有完成。")
    text = (final or unphased).strip()
    if not text:
        raise RuntimeError("Codex 没有返回正文。")
    return text, usage


def try_codex_backend() -> AgentBackend | None:
    if os.environ.get("GENI_STUDIO_BACKEND", "").strip().lower() != "codex":
        return None
    try:
        import openai_codex  # noqa: F401
    except ImportError:
        return None
    return CodexBackend()


def list_codex_models() -> dict:
    try:
        with _open_codex() as client:
            rows = _model_rows(client.models())
    except ImportError:
        return {"models": [], "source": "codex", "detail": "未安装 openai-codex。"}
    except Exception:  # noqa: BLE001 — 页面不回显 SDK 认证/网络细节
        return {"models": [], "source": "codex", "detail": "读不到模型列表。"}
    return {"models": rows, "source": "codex", "detail": ""}


def _codex_model(raw: str) -> str:
    text = raw.strip()
    return "" if text.lower() in {"", "default", "auto"} else text


def _interrupt(handle: Any) -> None:
    try:
        handle.interrupt()
    except Exception:  # noqa: BLE001 — 由 cancel 的 close 兜底
        return


def _cost_line(role_name: str, model: str, usage: Any) -> str:
    prefix = f"role={role_name} backend=codex model={model or 'default'}"
    last = usage.get("last") if isinstance(usage, dict) else getattr(usage, "last", None)
    if last is None:
        return f"{prefix} usage=unknown"
    if not isinstance(last, dict):
        last = last.model_dump()
    received = last.get("inputTokens", last.get("input_tokens"))
    sent = last.get("outputTokens", last.get("output_tokens"))
    if received is None or sent is None:
        return f"{prefix} usage=unknown"
    return f"{prefix} input_tokens={received} output_tokens={sent}"


def _model_rows(listed: Any) -> list[dict[str, str]]:
    # SDK 的 id 是目录条目 ID，model 才是请求模型名。
    return [
        {"id": item.model, "label": item.display_name or item.model}
        for item in listed.data if item.model
    ]
