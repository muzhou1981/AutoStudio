"""工作区权限：禁止推送远端，同一可写目录同时只允许一轮写入。"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

from geni_studio.workspace.layout import WorkspaceError


class WriteBusy(WorkspaceError):
    """可写目录已被另一轮持有。"""


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _read_lock_owner(lock_path: Path) -> dict[str, str]:
    if not lock_path.is_file():
        return {}
    try:
        raw = lock_path.read_text(encoding="utf-8").strip()
    except OSError:
        return {}
    owner: dict[str, str] = {}
    for part in raw.split():
        key, sep, value = part.partition("=")
        if sep:
            owner[key] = value
        elif "pid" not in owner:
            owner["pid"] = key
    return owner


def _read_lock_owner_pid(lock_path: Path) -> int | None:
    try:
        return int(_read_lock_owner(lock_path).get("pid", ""))
    except ValueError:
        return None


def _raise_write_busy(target_root: Path, lock_path: Path) -> None:
    owner = _read_lock_owner(lock_path)
    pid = _read_lock_owner_pid(lock_path)
    hint = ""
    if pid is not None:
        hint = f"（占用进程 PID {pid}"
        if owner.get("thread"):
            hint += f"，运行 {owner['thread']}"
        if not _pid_alive(pid):
            hint += "，登记进程已不在；请重启 geni-studio-web 后重试"
        hint += "）"
    raise WriteBusy(f"目标项目已有写入进行中: {target_root}{hint}")


def _lock_path(target_root: Path, lock_file: Path | None = None) -> Path:
    path = lock_file or target_root / ".geni_studio" / "write.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _try_lock(handle, wait_seconds: float) -> bool:
    import fcntl
    import time

    deadline = time.monotonic() + max(wait_seconds, 0)
    while True:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except BlockingIOError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.2)


def assert_write_available(target_root: Path, lock_file: Path | None = None) -> None:
    """启动前的快速失败探测，不持有锁；真正的互斥由 `exclusive_write` 保证。"""
    lock_path = _lock_path(target_root, lock_file)
    with lock_path.open("a", encoding="utf-8") as handle:
        import fcntl

        if not _try_lock(handle, 0):
            _raise_write_busy(target_root, lock_path)
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


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
def exclusive_write(
    target_root: Path, *, owner: str = "", wait_seconds: float = 0, lock_file: Path | None = None
):
    """同一可写目录同时只允许一个写入者；锁文件只记录当前持有者。"""
    import fcntl
    from datetime import UTC, datetime

    lock_path = _lock_path(target_root, lock_file)
    # 以追加模式打开，避免在拿到锁之前清掉持有者信息。
    handle = lock_path.open("a+", encoding="utf-8")
    try:
        if not _try_lock(handle, wait_seconds):
            _raise_write_busy(target_root, lock_path)
        handle.seek(0)
        handle.truncate()
        stamp = datetime.now(UTC).isoformat(timespec="seconds")
        handle.write(f"pid={os.getpid()} thread={owner or '-'} since={stamp}\n")
        handle.flush()
        try:
            yield
        finally:
            handle.seek(0)
            handle.truncate()
            handle.flush()
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        handle.close()
