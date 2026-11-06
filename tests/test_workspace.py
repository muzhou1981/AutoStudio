import os
import subprocess

from auto_studio.backends.cursor_backend import CursorBackend
from auto_studio.hitl.service import GraphRunService
from auto_studio.workflows.default import compile_graph, graph
from auto_studio.workspace.checkpoint import sqlite_checkpointer
from auto_studio.workspace.context import use_worktree


def test_start_persists_artifacts_and_worktree(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_STUDIO_WORKSPACE", "1")
    monkeypatch.setenv("AUTO_STUDIO_TARGET_ROOT", str(tmp_path))
    st = GraphRunService(graph).start(human_request="mul", scenario_key="npu_operator")
    worktree = st.values["workspace_path"]
    assert os.path.isdir(worktree)
    run_dir = tmp_path / ".auto_studio" / "runs" / st.thread_id
    spec = (run_dir / "requirement_spec.md").read_text(encoding="utf-8")
    assert "requirement" in spec or "stub" in spec or "需求" in spec
    assert (run_dir / "manifest.json").is_file()
    branch = subprocess.check_output(
        ["git", "-C", worktree, "rev-parse", "--abbrev-ref", "HEAD"],
        text=True,
    ).strip()
    assert branch == f"auto-studio/{st.thread_id}"


def test_sqlite_checkpoint_resumes(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTO_STUDIO_WORKSPACE", "0")
    db = tmp_path / "checkpoints.sqlite"
    svc = GraphRunService(compile_graph(sqlite_checkpointer(db)))
    st = svc.start(human_request="persist", scenario_key="npu_operator")
    again = GraphRunService(compile_graph(sqlite_checkpointer(db))).status(st.thread_id)
    assert again.phase == "awaiting_human"
    assert again.thread_id == st.thread_id


def test_cursor_defaults_to_auto_route_and_worktree_tools(tmp_path, monkeypatch):
    monkeypatch.setenv("CURSOR_API_KEY", "test-key")
    monkeypatch.setenv("AUTO_STUDIO_CURSOR_VERIFY", "0")
    monkeypatch.delenv("AUTO_STUDIO_CURSOR_MODEL", raising=False)
    captured: dict = {}

    class _Run:
        def text(self) -> str:
            return "ok"

    class _Agent:
        def send(self, prompt: str):
            return _Run()

    class _Client:
        def create_agent(self, opts, api_key=None):
            captured["opts"] = opts
            captured["api_key"] = api_key
            return _Agent()

    monkeypatch.setattr("cursor_sdk._client._default_client", lambda: _Client())
    backend = CursorBackend()
    with use_worktree(tmp_path):
        assert backend.complete(role_name="developer", system_prompt="s", user_prompt="u") == "ok"
    opts = captured["opts"]
    assert opts.model == "default"
    assert opts.tools is None
    assert os.fspath(opts.local.cwd) == str(tmp_path)
