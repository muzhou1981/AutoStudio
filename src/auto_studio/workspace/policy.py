"""工作区权限：禁止推送远端，同一目标同时只允许一轮写入。"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

from auto_studio.workspace.layout import WorkspaceError


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
    dot = target_root / ".auto_studio"
    dot.mkdir(parents=True, exist_ok=True)
    lock_path = dot / "write.lock"
    handle = lock_path.open("a", encoding="utf-8")
    try:
        import fcntl

        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise WorkspaceError(f"目标项目已有写入进行中: {target_root}") from exc
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
