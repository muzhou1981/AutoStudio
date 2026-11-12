"""一轮 Run 结束时回收 Agent、桥接与带标识的派生进程。"""

from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

from geni_studio.backends.run_processes import (
    RUN_ENV,
    bridge_command,
    reap_run,
    run_processes,
)

linux_only = pytest.mark.skipif(not sys.platform.startswith("linux"), reason="依赖 /proc")


def _detached(run_id: str) -> subprocess.Popen:
    env = {**os.environ, RUN_ENV: run_id}
    return subprocess.Popen(["sleep", "60"], env=env, start_new_session=True)


def _wait_gone(proc: subprocess.Popen) -> bool:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return True
        time.sleep(0.05)
    return False


def test_bridge_command_carries_run_marker() -> None:
    assert bridge_command("t-1", "/opt/bridge") == ["env", f"{RUN_ENV}=t-1", "/opt/bridge"]


@linux_only
def test_reap_run_kills_only_marked_processes_of_that_run() -> None:
    mine = _detached("lifecycle-a")
    other = _detached("lifecycle-b")
    try:
        assert mine.pid in run_processes("lifecycle-a")
        assert other.pid not in run_processes("lifecycle-a")
        assert reap_run("lifecycle-a") == 1
        assert _wait_gone(mine)
        assert other.poll() is None
    finally:
        for proc in (mine, other):
            if proc.poll() is None:
                proc.kill()
                proc.wait()


@linux_only
def test_reap_run_never_targets_this_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(RUN_ENV, "lifecycle-self")
    child = subprocess.Popen(["sleep", "60"], start_new_session=True)
    try:
        found = run_processes("lifecycle-self")
        assert os.getpid() not in found
        assert child.pid in found
    finally:
        child.kill()
        child.wait()


@linux_only
def test_live_processes_lists_marked_commands_without_bridges() -> None:
    from geni_studio.backends.run_processes import live_processes

    proc = _detached("lifecycle-live")
    try:
        rows = live_processes("lifecycle-live")
        assert [row["command"] for row in rows] == ["sleep 60"]
        assert rows[0]["pid"] == proc.pid and rows[0]["started_at"] > 0
    finally:
        proc.kill()
        proc.wait()


def test_task_step_keeps_reply_and_drops_subagent_transcript(tmp_path) -> None:
    import json

    from geni_studio.hitl.conversation import append_step, task_started_step

    path = tmp_path / "001.jsonl"
    args = {"description": "统计文件", "agentId": "sub-1"}
    append_step(path, task_started_step({"type": "task", "args": args}))
    append_step(path, {
        "type": "toolCall",
        "message": {
            "type": "task",
            "args": args,
            "result": {"status": "success", "value": {
                "agentId": "sub-1", "isBackground": False, "durationMs": 3064,
                "conversationSteps": [
                    {"thinkingMessage": {"text": "想"}},
                    {"toolCall": {"shellToolCall": {"args": {"command": "ls"}, "result": {"success": {"stdout": "RAW"}}}}},
                    {"assistantMessage": {"text": "数量：0"}},
                ],
            }},
        },
    })
    started, done = (json.loads(line)["step"] for line in path.read_text().splitlines())
    assert started == {"type": "taskStarted", "message": {"args": args}}
    value = done["message"]["result"]["value"]
    assert value == {"agentId": "sub-1", "isBackground": False, "durationMs": 3064, "toolCount": 1, "reply": "数量：0"}


class _Closable:
    def __init__(self, log: list[str], name: str) -> None:
        self._log = log
        self._name = name

    def close(self) -> None:
        self._log.append(self._name)


def test_release_run_closes_agents_and_bridge_of_that_run_only() -> None:
    from geni_studio.backends.cursor_backend import CursorBackend

    log: list[str] = []
    backend = CursorBackend.__new__(CursorBackend)
    import threading

    backend._lock = threading.Lock()
    backend._agents = {"a1": _Closable(log, "agent-a1"), "b1": _Closable(log, "agent-b1")}
    backend._agent_run = {"a1": "run-a", "b1": "run-b"}
    backend._role_sent = {"a1", "b1"}
    backend._send_locks = {}
    backend._bridges = {
        "run-a": (_Closable(log, "bridge-a"), _Closable(log, "client-a")),
        "run-b": (_Closable(log, "bridge-b"), _Closable(log, "client-b")),
    }
    backend.release_run("run-a")
    assert log == ["agent-a1", "client-a", "bridge-a"]
    assert set(backend._agents) == {"b1"}
    assert set(backend._bridges) == {"run-b"}
    assert backend._role_sent == {"b1"}


def test_reap_leftovers_keeps_unknown_runs_and_live_dev_servers(monkeypatch: pytest.MonkeyPatch) -> None:
    from geni_studio.backends import lifecycle

    owners = {11: "done", 12: "paused", 13: "paused", 14: "elsewhere"}
    reaped: list[list[int]] = []
    monkeypatch.setattr(lifecycle, "run_processes", lambda: owners)
    monkeypatch.setattr(lifecycle, "_is_bridge", lambda pid: pid == 13)
    monkeypatch.setattr(lifecycle, "reap", lambda pids: reaped.append(sorted(pids)) or len(pids))
    phases = {"done": "completed", "paused": "awaiting_human"}
    assert lifecycle.reap_leftovers(phases.get) == 2
    assert reaped == [[11, 13]]


def test_finished_run_releases_its_processes(monkeypatch: pytest.MonkeyPatch) -> None:
    from geni_studio.backends import lifecycle
    from geni_studio.hitl.service import GraphRunService

    released: list[str] = []
    monkeypatch.setattr(lifecycle, "release_run", lambda tid: released.append(tid) or 0)

    class _St:
        def __init__(self, phase: str) -> None:
            self.phase = phase

    for phase, expected in (("completed", ["t"]), ("stopped", ["t"]), ("awaiting_human", [])):
        released.clear()
        svc = GraphRunService.__new__(GraphRunService)
        monkeypatch.setattr(svc, "status", lambda tid, p=phase: _St(p), raising=False)
        monkeypatch.setattr(svc, "_index", lambda tid, st: None, raising=False)
        monkeypatch.setattr(svc, "notify_change", lambda tid: None, raising=False)
        svc._done("t")
        assert released == expected, phase
