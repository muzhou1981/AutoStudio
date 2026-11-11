"""后端会话的身份、落盘与互斥（Cursor Agent、Codex Thread 共用）。"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


def current_node_id() -> str:
    from langgraph.config import get_config

    try:
        return str((get_config().get("metadata") or {}).get("langgraph_node") or "")
    except RuntimeError:
        return ""


def session_digest(identity: list[Any]) -> str:
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()


def session_path(kind: str, run_id: str, cwd: str, digest: str) -> Path:
    from geni_studio.hitl.conversation import conversation_dir

    return conversation_dir(run_id, cwd).parent / kind / f"{digest}.json"


@contextmanager
def session_lock(path: Path | None) -> Iterator[None]:
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


def load_session(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_session(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
