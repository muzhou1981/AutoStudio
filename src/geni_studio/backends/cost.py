"""单次后端调用的成本记录。"""

from __future__ import annotations

from contextvars import ContextVar

_lines: ContextVar[list[str] | None] = ContextVar("geni_studio_cost_lines", default=None)
_project: ContextVar[str] = ContextVar("geni_studio_project_id", default="")


def set_project_id(project_id: str) -> object:
    return _project.set(project_id)


def current_project_id() -> str:
    return _project.get()


def reset_project_id(token: object) -> None:
    _project.reset(token)  # type: ignore[arg-type]


def begin_cost_log() -> object:
    return _lines.set([])


def note_cost(line: str) -> None:
    bucket = _lines.get()
    if bucket is None:
        bucket = []
        _lines.set(bucket)
    bucket.append(line)


def take_cost_lines() -> list[str]:
    return list(_lines.get() or [])


def end_cost_log(token: object) -> None:
    _lines.reset(token)  # type: ignore[arg-type]
