"""运行时持久化：任务队列、停止与暂停请求、运行索引。

与检查点同目录的 `runtime.sqlite`；内存检查点（测试）对应一个进程内的内存库。
Web 进程与独立执行进程通过这张库协作。
"""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import threading
import time
import uuid
import weakref
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS run_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT 'null',
    state TEXT NOT NULL DEFAULT 'queued',
    worker TEXT NOT NULL DEFAULT '',
    error TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    attempts INTEGER NOT NULL DEFAULT 0,
    not_before REAL NOT NULL DEFAULT 0,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS run_jobs_state ON run_jobs(state, not_before, id);
CREATE INDEX IF NOT EXISTS run_jobs_thread ON run_jobs(thread_id, state);
CREATE TABLE IF NOT EXISTS run_controls (
    thread_id TEXT PRIMARY KEY,
    stop INTEGER NOT NULL DEFAULT 0,
    pause INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS run_index (
    thread_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL DEFAULT '',
    run_name TEXT NOT NULL DEFAULT '',
    phase TEXT NOT NULL DEFAULT '',
    current TEXT NOT NULL DEFAULT '',
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS run_index_project ON run_index(project_id, updated_at);
CREATE TABLE IF NOT EXISTS runtime_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

ACTIVE_STATES = ("queued", "running")


def worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


def _worker_alive(worker: str) -> bool:
    host, _, rest = worker.partition(":")
    pid_text = rest.partition(":")[0]
    if host != socket.gethostname():
        return True
    try:
        pid = int(pid_text)
    except ValueError:
        return False
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


@dataclass
class Job:
    id: int
    thread_id: str
    kind: str
    payload: Any = None
    state: str = "queued"
    worker: str = ""
    error: str = ""
    note: str = ""
    attempts: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class IndexRow:
    thread_id: str
    project_id: str
    run_name: str
    phase: str
    current: str
    updated_at: float


class RuntimeStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = threading.RLock()
        with self._lock:
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    # --- 任务 ---

    def enqueue(self, thread_id: str, kind: str, payload: Any = None) -> Job:
        now = time.time()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO run_jobs(thread_id, kind, payload, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (thread_id, kind, json.dumps(payload, ensure_ascii=False, default=str), now, now),
            )
            self._conn.commit()
            return Job(id=int(cur.lastrowid or 0), thread_id=thread_id, kind=kind, payload=payload)

    def claim(self, worker: str, *, job_id: int | None = None) -> Job | None:
        """领取一个可执行的任务；同一轮同时只执行一个任务，按入队顺序。"""
        now = time.time()
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                if job_id is not None:
                    row = self._conn.execute(
                        "SELECT * FROM run_jobs WHERE id = ? AND state = 'queued'", (job_id,)
                    ).fetchone()
                else:
                    row = self._conn.execute(
                        """
                        SELECT * FROM run_jobs AS j
                        WHERE j.state = 'queued' AND j.not_before <= ?
                          AND NOT EXISTS (
                            SELECT 1 FROM run_jobs AS r WHERE r.thread_id = j.thread_id AND r.state = 'running'
                          )
                          AND j.id = (
                            SELECT MIN(q.id) FROM run_jobs AS q
                            WHERE q.thread_id = j.thread_id AND q.state = 'queued'
                          )
                        ORDER BY j.id LIMIT 1
                        """,
                        (now,),
                    ).fetchone()
                if row is None:
                    self._conn.execute("COMMIT")
                    return None
                self._conn.execute(
                    "UPDATE run_jobs SET state = 'running', worker = ?, attempts = attempts + 1, updated_at = ? "
                    "WHERE id = ?",
                    (worker, now, row["id"]),
                )
                self._conn.execute("COMMIT")
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
        job = _job(row)
        job.state, job.worker = "running", worker
        return job

    def finish(self, job_id: int, *, error: str = "") -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE run_jobs SET state = ?, error = ?, updated_at = ? WHERE id = ?",
                ("failed" if error else "done", error, time.time(), job_id),
            )
            self._conn.commit()

    def defer(self, job_id: int, *, seconds: float, note: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE run_jobs SET state = 'queued', worker = '', note = ?, not_before = ?, updated_at = ? "
                "WHERE id = ?",
                (note, time.time() + seconds, time.time(), job_id),
            )
            self._conn.commit()

    def active_job(self, thread_id: str) -> Job | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM run_jobs WHERE thread_id = ? AND state IN ('queued', 'running') ORDER BY id LIMIT 1",
                (thread_id,),
            ).fetchone()
        return _job(row) if row is not None else None

    def last_job(self, thread_id: str) -> Job | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM run_jobs WHERE thread_id = ? ORDER BY id DESC LIMIT 1", (thread_id,)
            ).fetchone()
        return _job(row) if row is not None else None

    def running_threads(self, worker: str = "") -> list[str]:
        sql = "SELECT DISTINCT thread_id FROM run_jobs WHERE state = 'running'"
        args: tuple[Any, ...] = ()
        if worker:
            sql += " AND worker = ?"
            args = (worker,)
        with self._lock:
            return [str(row[0]) for row in self._conn.execute(sql, args).fetchall()]

    def recover_orphans(self) -> list[Job]:
        """执行进程已退出、仍标为执行中的任务记为失败并返回。"""
        with self._lock:
            rows = self._conn.execute("SELECT * FROM run_jobs WHERE state = 'running'").fetchall()
        orphans = [_job(row) for row in rows if not _worker_alive(str(row["worker"]))]
        for job in orphans:
            self.finish(job.id, error="执行进程已退出，任务未完成")
        return orphans

    def forget_thread(self, thread_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM run_jobs WHERE thread_id = ?", (thread_id,))
            self._conn.execute("DELETE FROM run_controls WHERE thread_id = ?", (thread_id,))
            self._conn.execute("DELETE FROM run_index WHERE thread_id = ?", (thread_id,))
            self._conn.execute("DELETE FROM runtime_meta WHERE key LIKE ?", (f"%:{thread_id}",))
            self._conn.commit()

    def prune_jobs(self, *, keep_seconds: float = 7 * 24 * 3600) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM run_jobs WHERE state IN ('done', 'failed') AND updated_at < ?",
                (time.time() - keep_seconds,),
            )
            self._conn.commit()

    # --- 停止与暂停请求 ---

    def set_control(self, thread_id: str, *, stop: bool | None = None, pause: bool | None = None) -> None:
        with self._lock:
            current = self._conn.execute(
                "SELECT stop, pause FROM run_controls WHERE thread_id = ?", (thread_id,)
            ).fetchone()
            new_stop = int(stop if stop is not None else (current["stop"] if current else 0))
            new_pause = int(pause if pause is not None else (current["pause"] if current else 0))
            self._conn.execute(
                "INSERT INTO run_controls(thread_id, stop, pause, updated_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(thread_id) DO UPDATE SET stop = excluded.stop, pause = excluded.pause, "
                "updated_at = excluded.updated_at",
                (thread_id, new_stop, new_pause, time.time()),
            )
            self._conn.commit()

    def controls(self, thread_id: str) -> tuple[bool, bool]:
        with self._lock:
            row = self._conn.execute(
                "SELECT stop, pause FROM run_controls WHERE thread_id = ?", (thread_id,)
            ).fetchone()
        if row is None:
            return False, False
        return bool(row["stop"]), bool(row["pause"])

    # --- 运行索引 ---

    def upsert_index(self, thread_id: str, *, project_id: str, run_name: str, phase: str, current: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO run_index(thread_id, project_id, run_name, phase, current, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(thread_id) DO UPDATE SET project_id = excluded.project_id, "
                "run_name = excluded.run_name, phase = excluded.phase, current = excluded.current, "
                "updated_at = excluded.updated_at",
                (thread_id, project_id, run_name, phase, current, time.time()),
            )
            self._conn.commit()

    def index_rows(self, *, project_id: str = "") -> list[IndexRow]:
        sql = "SELECT * FROM run_index"
        args: tuple[Any, ...] = ()
        if project_id:
            sql += " WHERE project_id = ?"
            args = (project_id,)
        sql += " ORDER BY updated_at DESC"
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        return [
            IndexRow(
                thread_id=str(row["thread_id"]),
                project_id=str(row["project_id"]),
                run_name=str(row["run_name"]),
                phase=str(row["phase"]),
                current=str(row["current"]),
                updated_at=float(row["updated_at"]),
            )
            for row in rows
        ]

    def taken_names(self, project_id: str) -> set[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT run_name FROM run_index WHERE project_id = ?", (project_id,)
            ).fetchall()
        return {str(row[0]) for row in rows if str(row[0]).strip()}

    def meta(self, key: str) -> str:
        with self._lock:
            row = self._conn.execute("SELECT value FROM runtime_meta WHERE key = ?", (key,)).fetchone()
        return str(row[0]) if row else ""

    def set_meta(self, key: str, value: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO runtime_meta(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )
            self._conn.commit()


def _job(row: sqlite3.Row) -> Job:
    return Job(
        id=int(row["id"]),
        thread_id=str(row["thread_id"]),
        kind=str(row["kind"]),
        payload=json.loads(row["payload"] or "null"),
        state=str(row["state"]),
        worker=str(row["worker"]),
        error=str(row["error"]),
        note=str(row["note"]),
        attempts=int(row["attempts"]),
    )


def _connect(target: str) -> sqlite3.Connection:
    conn = sqlite3.connect(target, check_same_thread=False, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    if target != ":memory:":
        conn.execute("PRAGMA journal_mode=WAL")
    return conn


_by_path: dict[str, RuntimeStore] = {}
_by_saver: weakref.WeakKeyDictionary[Any, RuntimeStore] = weakref.WeakKeyDictionary()
_guard = threading.Lock()


def _checkpoint_file(saver: Any) -> str:
    conn = getattr(saver, "conn", None)
    if not isinstance(conn, sqlite3.Connection):
        return ""
    for row in conn.execute("PRAGMA database_list").fetchall():
        if row[1] == "main" and row[2]:
            return str(row[2])
    return ""


def store_for_saver(saver: Any) -> RuntimeStore:
    """检查点库旁的运行时库；内存检查点各自对应一个内存库。"""
    path = _checkpoint_file(saver)
    with _guard:
        if path:
            runtime = os.fspath(Path(path).with_name("runtime.sqlite"))
            store = _by_path.get(runtime)
            if store is None:
                store = RuntimeStore(_connect(runtime))
                _by_path[runtime] = store
            return store
        store = _by_saver.get(saver)
        if store is None:
            store = RuntimeStore(_connect(":memory:"))
            _by_saver[saver] = store
        return store
