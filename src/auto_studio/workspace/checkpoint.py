"""LangGraph 检查点：默认 SQLite，测试可切回内存。"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver

from auto_studio.config.context import factory_root

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


def default_checkpointer() -> BaseCheckpointSaver:
    mode = os.environ.get("AUTO_STUDIO_CHECKPOINT", "sqlite").strip().lower()
    if mode == "memory":
        return MemorySaver()
    return sqlite_checkpointer(factory_root() / "runs" / "checkpoints.sqlite")
