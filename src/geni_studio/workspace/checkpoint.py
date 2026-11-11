"""LangGraph 检查点：默认 SQLite，测试可切回内存。"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver

from geni_studio.config.context import factory_root

_connections: dict[str, sqlite3.Connection] = {}


def sqlite_checkpointer(path: Path) -> BaseCheckpointSaver:
    path.parent.mkdir(parents=True, exist_ok=True)
    key = os.fspath(path.resolve())
    conn = _connections.get(key)
    if conn is None:
        conn = sqlite3.connect(key, check_same_thread=False)
        _connections[key] = conn
    from langgraph.checkpoint.sqlite import SqliteSaver

    return SqliteSaver(conn)


def checkpoint_file() -> Path | None:
    """默认检查点库的位置；内存检查点返回 None。"""
    if os.environ.get("GENI_STUDIO_CHECKPOINT", "sqlite").strip().lower() == "memory":
        return None
    raw = os.environ.get("GENI_STUDIO_CHECKPOINT_PATH", "").strip()
    return Path(raw) if raw else factory_root() / "runs" / "checkpoints.sqlite"


def default_checkpointer() -> BaseCheckpointSaver:
    path = checkpoint_file()
    if path is None:
        return MemorySaver()
    return sqlite_checkpointer(path)
