"""Cursor 后端进程级复用与会话续接（C4）。"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("cursor_sdk")


class _Run:
    def text(self) -> str:
        return "ok"


class _Agent:
    def __init__(self, agent_id: str, prompts: list[str]) -> None:
        self.agent_id = agent_id
        self._prompts = prompts

    def send(self, prompt: str, options=None) -> _Run:
        self._prompts.append(prompt)
        return _Run()


class _Client:
    def __init__(self) -> None:
        self.created = 0
        self.resumed: list[str] = []
        self.prompts: list[str] = []

    def create_agent(self, opts, api_key=None):
        self.created += 1
        return _Agent(f"agent-{self.created}", self.prompts)

    def resume_agent(self, agent_id, options=None):
        self.resumed.append(agent_id)
        return _Agent(agent_id, self.prompts)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> _Client:
    fake = _Client()
    monkeypatch.setenv("CURSOR_API_KEY", "test-key")
    monkeypatch.setattr("cursor_sdk._client._default_client", lambda: fake)
    return fake


def test_backend_is_reused_and_verified_once(client: _Client, monkeypatch: pytest.MonkeyPatch) -> None:
    from cursor_sdk import Cursor

    from geni_studio.backends.cursor_backend import try_cursor_backend

    calls = {"me": 0}

    def _me(**kwargs: object) -> object:
        calls["me"] += 1
        return object()

    monkeypatch.setenv("GENI_STUDIO_CURSOR_VERIFY", "1")
    monkeypatch.setattr(Cursor, "me", staticmethod(_me))
    first = try_cursor_backend(force=True)
    second = try_cursor_backend(force=True)
    assert first is not None and first is second
    assert calls["me"] == 1


def test_agent_is_resumed_from_disk_by_a_new_backend(client: _Client, tmp_path: Path, monkeypatch) -> None:
    from geni_studio.backends.cursor_backend import CursorBackend
    from geni_studio.hitl.control import bind_thread, unbind_thread
    from geni_studio.workspace.context import use_worktree

    monkeypatch.setenv("GENI_STUDIO_CURSOR_VERIFY", "0")
    (tmp_path / ".geni_studio").mkdir()
    token = bind_thread("run-1")
    try:
        with use_worktree(tmp_path):
            CursorBackend().complete(role_name="architect", system_prompt="角色定义", user_prompt="写设计")
            CursorBackend().complete(role_name="architect", system_prompt="角色定义", user_prompt="写计划")
            CursorBackend().complete(role_name="architect", system_prompt="新版角色定义", user_prompt="再写")
    finally:
        unbind_thread(token)
    assert client.created == 2
    assert client.resumed == ["agent-1"]
    assert client.prompts[0].startswith("角色定义")
    assert client.prompts[1] == "## 本轮任务\n\n写计划"
    assert client.prompts[2].startswith("新版角色定义")
    saved = list((tmp_path / ".geni_studio" / "runs" / "run-1" / "cursor-sessions").glob("*.json"))
    assert len(saved) == 2
