"""本轮停止与暂停标记。图节点与模型调用据此收束，不在这里改检查点。"""

from __future__ import annotations

import threading
from contextvars import ContextVar

_lock = threading.Lock()
_stop_requests: set[str] = set()
_pause_requests: set[str] = set()
_inflight: set[str] = set()
_active_runs: dict[str, list[object]] = {}
_thread_id: ContextVar[str] = ContextVar("geni_studio_run_thread", default="")


class RunStopped(RuntimeError):
    """操作者已要求停止本轮。"""


class RunPaused(RuntimeError):
    """操作者已要求暂停。当前调用可以结束，但不得进入下一节点。"""


def current_thread_id() -> str:
    return _thread_id.get()


def bind_thread(thread_id: str):
    return _thread_id.set(thread_id)


def unbind_thread(token) -> None:
    _thread_id.reset(token)


def request_stop(thread_id: str) -> bool:
    """记下停止请求。返回值表示这轮是否正在执行图。"""
    with _lock:
        _stop_requests.add(thread_id)
        return thread_id in _inflight


def is_stop_requested(thread_id: str | None = None) -> bool:
    tid = thread_id if thread_id is not None else _thread_id.get()
    if not tid:
        return False
    with _lock:
        return tid in _stop_requests


def clear_stop_request(thread_id: str) -> None:
    with _lock:
        _stop_requests.discard(thread_id)


def request_pause(thread_id: str) -> bool:
    """记下暂停请求。返回值表示这轮是否正在执行图。"""
    with _lock:
        _pause_requests.add(thread_id)
        return thread_id in _inflight


def is_pause_requested(thread_id: str | None = None) -> bool:
    tid = thread_id if thread_id is not None else _thread_id.get()
    if not tid:
        return False
    with _lock:
        return tid in _pause_requests


def clear_pause_request(thread_id: str) -> None:
    with _lock:
        _pause_requests.discard(thread_id)


def is_inflight(thread_id: str) -> bool:
    with _lock:
        return thread_id in _inflight


def enter_inflight(thread_id: str) -> bool:
    """进入图执行。返回值表示进入前已经要求停止。"""
    with _lock:
        _inflight.add(thread_id)
        return thread_id in _stop_requests


def leave_inflight(thread_id: str) -> None:
    with _lock:
        _inflight.discard(thread_id)


def register_active_run(thread_id: str, run: object) -> None:
    if not thread_id:
        return
    with _lock:
        _active_runs.setdefault(thread_id, []).append(run)


def unregister_active_run(thread_id: str, run: object) -> None:
    if not thread_id:
        return
    with _lock:
        runs = _active_runs.get(thread_id)
        if not runs:
            return
        try:
            runs.remove(run)
        except ValueError:
            return
        if not runs:
            _active_runs.pop(thread_id, None)


def cancel_active_runs(thread_id: str) -> None:
    with _lock:
        runs = list(_active_runs.get(thread_id, ()))
    for run in runs:
        cancel = getattr(run, "cancel", None)
        if callable(cancel):
            cancel()
