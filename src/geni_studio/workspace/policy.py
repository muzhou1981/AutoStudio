"""工作区权限：禁止推送远端，同一目标同时只允许一轮写入。"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

from geni_studio.workspace.layout import WorkspaceError


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _read_lock_owner_pid(lock_path: Path) -> int | None:
    if not lock_path.is_file():
        return None
    try:
        raw = lock_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not raw:
        return None
    try:
        return int(raw.split()[0])
    except ValueError:
        return None


def _raise_write_busy(target_root: Path, lock_path: Path) -> None:
    owner = _read_lock_owner_pid(lock_path)
    hint = ""
    if owner is not None:
        hint = f"（占用进程 PID {owner}"
        if not _pid_alive(owner):
            hint += "，登记进程已不在；请重启 geni-studio-web 后重试"
        hint += "）"
    raise WorkspaceError(f"目标项目已有写入进行中: {target_root}{hint}")


def assert_write_available(target_root: Path) -> None:
    """占用写入锁探测；不可用则抛出 WorkspaceError，不持有锁。"""
    dot = target_root / ".geni_studio"
    dot.mkdir(parents=True, exist_ok=True)
    lock_path = dot / "write.lock"
    handle = lock_path.open("a", encoding="utf-8")
    try:
        import fcntl

        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            _raise_write_busy(target_root, lock_path)
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def reject_remote_push(argv: list[str]) -> None:
    """工厂托管的命令不得 git push。"""
    if not argv:
        return
    name = Path(argv[0]).name
    if name != "git":
        return
    args = argv[1:]
    if args and args[0] == "-C" and len(args) >= 3:
        args = args[2:]
    while args and args[0].startswith("-"):
        args = args[1:]
    if not args:
        return
    if args[0] == "push" or (args[0] == "remote" and "push" in args):
        raise WorkspaceError("工厂工作区禁止推送远端")


@contextmanager
def exclusive_write(target_root: Path):
    """同一目标项目同时只允许一个写入者。"""
    dot = target_root / ".geni_studio"
    dot.mkdir(parents=True, exist_ok=True)
    lock_path = dot / "write.lock"
    handle = lock_path.open("a", encoding="utf-8")
    try:
        import fcntl

        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            _raise_write_busy(target_root, lock_path)
        handle.write(str(os.getpid()))
        handle.flush()
        yield
    finally:
        try:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        handle.close()
