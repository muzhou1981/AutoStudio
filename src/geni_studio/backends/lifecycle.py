"""一轮 Run 结束后回收它占用的 Agent、桥接进程与派生进程。"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path

from geni_studio.backends.run_processes import RUN_ENV, reap, reap_run, run_processes

log = logging.getLogger(__name__)


def _cursor_backends() -> list[object]:
    from geni_studio.backends.cursor_backend import _cache_lock, _cached

    with _cache_lock:
        return list(_cached.values())


def release_run(thread_id: str) -> int:
    """关闭这一轮的 Agent 与桥接，再结束带这一轮标识的进程。返回结束的进程数。"""
    if not thread_id:
        return 0
    for backend in _cursor_backends():
        release = getattr(backend, "release_run", None)
        if callable(release):
            try:
                release(thread_id)
            except Exception:
                log.exception("关闭 Run %s 的 Agent 失败", thread_id)
    count = reap_run(thread_id)
    if count:
        log.info("Run %s 结束，回收 %d 个进程", thread_id, count)
    return count


def reap_leftovers(phase_of: Callable[[str], str | None]) -> int:
    """服务启动时调用，此时本进程还没有为任何一轮启动桥接。

    所属 Run 已结束的进程全部回收；Run 未结束的只回收上一次服务留下的桥接，
    它们的回调地址已失效，开发服务等进程留给续跑。所属 Run 不在本服务中的不动。
    """
    pids = []
    for pid, run in run_processes().items():
        phase = phase_of(run)
        if phase is None:
            continue
        if phase in ("completed", "rejected", "stopped") or _is_bridge(pid):
            pids.append(pid)
    count = reap(pids) if pids else 0
    if count:
        log.info("回收上一次服务遗留的 %d 个进程", count)
    return count


def _is_bridge(pid: int) -> bool:
    try:
        cmdline = (Path("/proc") / str(pid) / "cmdline").read_bytes()
    except OSError:
        return False
    return b"cursor-sdk-bridge" in cmdline


def forget_parent_run() -> None:
    """服务本身若由某一轮的 Agent 启动，不让默认桥接继承那一轮的标识。"""
    os.environ.pop(RUN_ENV, None)


def close_all() -> None:
    for backend in _cursor_backends():
        close = getattr(backend, "close_all", None)
        if callable(close):
            try:
                close()
            except Exception:
                log.exception("关闭 Cursor 桥接失败")
