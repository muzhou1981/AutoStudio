"""一轮 Run 启动的进程：按环境变量标记，结束时回收。

Agent 的 Shell 继承桥接进程的环境；`nohup … &` 启动的进程会脱离 Agent 自成会话，
关闭 Agent 或桥接都结束不了它们。每一轮使用带 ``GENI_STUDIO_RUN=<thread_id>`` 的桥接，
这一轮派生的进程都继承该变量，回收时按它在 ``/proc`` 中查找。
"""

from __future__ import annotations

import os
import signal
import time
from pathlib import Path

RUN_ENV = "GENI_STUDIO_RUN"

_PROC = Path("/proc")


def bridge_command(thread_id: str, bridge: str) -> list[str]:
    return ["env", f"{RUN_ENV}={thread_id}", bridge]


def _run_of(pid: int) -> str | None:
    try:
        raw = (_PROC / str(pid) / "environ").read_bytes()
    except OSError:
        return None
    prefix = (RUN_ENV + "=").encode()
    for item in raw.split(b"\0"):
        if item.startswith(prefix):
            return item[len(prefix):].decode(errors="replace")
    return None


def _ancestors() -> set[int]:
    seen = {os.getpid()}
    pid = os.getpid()
    while pid > 1:
        try:
            stat = (_PROC / str(pid) / "stat").read_text()
        except OSError:
            break
        pid = int(stat.rsplit(")", 1)[1].split()[1])
        seen.add(pid)
    return seen


def run_processes(thread_id: str | None = None) -> dict[int, str]:
    """本用户进程中带标记的 pid 与其所属 Run；``thread_id`` 给定时只取这一轮。"""
    if not _PROC.is_dir():
        return {}
    uid = os.getuid()
    skip = _ancestors()
    found: dict[int, str] = {}
    for entry in _PROC.iterdir():
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        if pid in skip:
            continue
        try:
            if entry.stat().st_uid != uid:
                continue
        except OSError:
            continue
        run = _run_of(pid)
        if run and (thread_id is None or run == thread_id):
            found[pid] = run
    return found


def reap(pids: list[int], *, grace_seconds: float = 2.0) -> int:
    """先 SIGTERM，宽限期后仍在的再 SIGKILL。返回发出信号的进程数。"""
    signalled = []
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
            signalled.append(pid)
        except (ProcessLookupError, PermissionError):
            continue
    deadline = time.monotonic() + grace_seconds
    alive = list(signalled)
    while alive and time.monotonic() < deadline:
        time.sleep(0.1)
        alive = [pid for pid in alive if _alive(pid)]
    for pid in alive:
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            continue
    return len(signalled)


def _alive(pid: int) -> bool:
    try:
        state = (_PROC / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()[0]
    except OSError:
        return False
    return state != "Z"


def live_processes(thread_id: str) -> list[dict]:
    """这一轮仍在运行的进程（不含桥接本身），供运行页展示：pid、命令、启动时刻（Unix 秒）。"""
    if not thread_id:
        return []
    boot = 0
    try:
        for line in (_PROC / "stat").read_text().splitlines():
            if line.startswith("btime "):
                boot = int(line.split()[1])
    except (OSError, ValueError):
        boot = 0
    ticks = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
    rows = []
    for pid in sorted(run_processes(thread_id)):
        try:
            argv = (_PROC / str(pid) / "cmdline").read_bytes().split(b"\0")
            stat = (_PROC / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()
        except OSError:
            continue
        command = " ".join(part.decode(errors="replace") for part in argv if part)
        if not command or "cursor-sdk-bridge" in command or stat[0] == "Z":
            continue
        started = boot + int(stat[19]) // ticks if boot and len(stat) > 19 else 0
        rows.append({"pid": pid, "command": command[:300], "started_at": started})
    return rows


def reap_run(thread_id: str) -> int:
    if not thread_id:
        return 0
    return reap(list(run_processes(thread_id)))
