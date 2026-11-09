"""当前 Run 的工作树路径（供后端把工具作用域限制在目标项目）。"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

_worktree: ContextVar[str] = ContextVar("geni_studio_worktree", default="")


def current_worktree() -> str:
    return _worktree.get()


@contextmanager
def use_worktree(path: Path | str):
    token = _worktree.set(os_fspath(path))
    try:
        yield
    finally:
        _worktree.reset(token)


def os_fspath(path: Path | str) -> str:
    return path if isinstance(path, str) else str(path)
