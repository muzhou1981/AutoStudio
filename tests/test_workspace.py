import os
import subprocess
from pathlib import Path

import pytest

from geni_studio.backends.cursor_backend import CursorBackend
from geni_studio.hitl.service import GraphRunService
from geni_studio.workflows.default import compile_graph, graph
from geni_studio.workspace.checkpoint import sqlite_checkpointer
from geni_studio.workspace.context import use_worktree


def test_start_persists_artifacts_and_worktree(tmp_path, monkeypatch):
    monkeypatch.setenv("GENI_STUDIO_WORKSPACE", "1")
    monkeypatch.setenv("GENI_STUDIO_TARGET_ROOT", str(tmp_path))
    st = GraphRunService(graph).start(human_request="mul", scenario_key="npu_operator")
    worktree = st.values["workspace_path"]
    assert os.path.isdir(worktree)
    run_dir = tmp_path / ".geni_studio" / "runs" / st.thread_id
    spec = (run_dir / "artifacts" / "requirement_spec.md").read_text(encoding="utf-8")
    assert "requirement" in spec or "stub" in spec or "需求" in spec
    assert (run_dir / "manifest.json").is_file()
    branch = subprocess.check_output(
        ["git", "-C", worktree, "rev-parse", "--abbrev-ref", "HEAD"],
        text=True,
    ).strip()
    assert branch == f"geni-studio/{st.thread_id}"


def test_self_improve_starts_on_the_current_branch(tmp_path, monkeypatch):
    monkeypatch.setenv("GENI_STUDIO_WORKSPACE", "1")
    monkeypatch.setenv("GENI_STUDIO_TARGET_ROOT", str(tmp_path))
    monkeypatch.setenv("GENI_STUDIO_BACKEND", "stub")
    from geni_studio.config.context import build_run_context

    def wrapped(*args, **kwargs):
        ctx = build_run_context(*args, **kwargs)
        workflow = dict(ctx.merged.get("workflow") or {})
        workflow["profile_id"] = "self_improve"
        ctx.merged["workflow"] = workflow
        return ctx

    monkeypatch.setattr("geni_studio.config.context.build_run_context", wrapped)
    st = GraphRunService(graph).start(human_request="改一处说明")
    assert st.phase == "awaiting_human"
    assert Path(st.values["workspace_path"]) == tmp_path.resolve()
    assert st.values["base_branch"]
    assert not (tmp_path / ".geni_studio" / "worktrees").exists()
    assert (tmp_path / ".geni_studio" / "runs" / st.thread_id / "base_branch.txt").is_file()


def test_current_branch_layout_commits_after_approval(tmp_path):
    from geni_studio.workspace.layout import (
        commit_current_branch,
        prepare_run_layout,
    )

    layout = prepare_run_layout(tmp_path, "run1", on_current_branch=True)
    assert layout.worktree == tmp_path.resolve()
    assert not (tmp_path / ".geni_studio" / "worktrees").exists()
    (tmp_path / "note.txt").write_text("已改\n", encoding="utf-8")
    record = commit_current_branch(str(layout.worktree), layout.base_branch, "补上一行说明")
    assert "已由程序员" in record
    assert "没有未提交" not in record
    shown = subprocess.check_output(
        ["git", "-C", os.fspath(tmp_path), "show", "HEAD:note.txt"],
        text=True,
    )
    assert shown == "已改\n"
    branch = subprocess.check_output(
        ["git", "-C", os.fspath(tmp_path), "rev-parse", "--abbrev-ref", "HEAD"],
        text=True,
    ).strip()
    assert branch == layout.base_branch
    empty = commit_current_branch(str(layout.worktree), layout.base_branch, "")
    assert "没有未提交" in empty


def test_current_branch_allows_dirty_start_but_refuses_commit_on_wrong_branch(tmp_path):
    from geni_studio.workspace.layout import (
        WorkspaceError,
        commit_current_branch,
        prepare_run_layout,
    )

    layout = prepare_run_layout(tmp_path, "run1", on_current_branch=True)
    (tmp_path / "dirty.txt").write_text("先写着\n", encoding="utf-8")
    layout2 = prepare_run_layout(tmp_path, "run2", on_current_branch=True)
    assert layout2.base_branch == layout.base_branch
    subprocess.check_call(["git", "-C", os.fspath(tmp_path), "checkout", "-b", "other"])
    with pytest.raises(WorkspaceError, match="拒绝提交"):
        commit_current_branch(os.fspath(tmp_path), layout.base_branch, "不该提交")


def _show(repo, ref, name):
    return subprocess.check_output(["git", "-C", os.fspath(repo), "show", f"{ref}:{name}"], text=True)


def test_worktree_lands_on_the_starting_branch(tmp_path):
    from geni_studio.workspace.layout import land_worktree, prepare_run_layout

    layout = prepare_run_layout(tmp_path, "run1")
    start = subprocess.check_output(["git", "-C", os.fspath(tmp_path), "rev-parse", "--abbrev-ref", "HEAD"], text=True)
    marker = tmp_path / ".geni_studio" / "runs" / "run1" / "land_branch.txt"
    assert marker.read_text(encoding="utf-8").strip() == start.strip()
    (layout.worktree / "feature.txt").write_text("新功能\n", encoding="utf-8")
    record = land_worktree(os.fspath(layout.worktree), "加上新功能")
    assert "geni-studio/run1" in record and f"并合并到 {start.strip()}" in record
    assert _show(tmp_path, "HEAD", "feature.txt") == "新功能\n"
    assert (tmp_path / "feature.txt").read_text(encoding="utf-8") == "新功能\n"
    assert "没有新的提交" in land_worktree(os.fspath(layout.worktree), "")


def test_worktree_landing_refuses_dirty_target_and_keeps_branch(tmp_path):
    from geni_studio.workspace.layout import (
        WorkspaceError,
        land_worktree,
        prepare_run_layout,
    )

    layout = prepare_run_layout(tmp_path, "run1")
    (layout.worktree / "feature.txt").write_text("新功能\n", encoding="utf-8")
    (tmp_path / "local.txt").write_text("人正在改\n", encoding="utf-8")
    with pytest.raises(WorkspaceError, match="未提交的改动"):
        land_worktree(os.fspath(layout.worktree), "加上新功能")
    assert _show(tmp_path, "geni-studio/run1", "feature.txt") == "新功能\n"
    assert not (tmp_path / "feature.txt").exists()


def test_worktree_landing_aborts_on_conflict(tmp_path):
    from geni_studio.workspace.layout import (
        WorkspaceError,
        land_worktree,
        prepare_run_layout,
    )

    layout = prepare_run_layout(tmp_path, "run1")
    (layout.worktree / "same.txt").write_text("工作树\n", encoding="utf-8")
    (tmp_path / "same.txt").write_text("主分支\n", encoding="utf-8")
    subprocess.check_call(["git", "-C", os.fspath(tmp_path), "add", "same.txt"])
    subprocess.check_call(
        ["git", "-C", os.fspath(tmp_path), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "main"]
    )
    with pytest.raises(WorkspaceError, match="有冲突，已撤销合并：same.txt"):
        land_worktree(os.fspath(layout.worktree), "冲突")
    assert not (tmp_path / ".git" / "MERGE_HEAD").exists()
    assert (tmp_path / "same.txt").read_text(encoding="utf-8") == "主分支\n"


def test_spec_kit_run_lands_worktree_changes_after_acceptance(tmp_path, monkeypatch):
    monkeypatch.setenv("GENI_STUDIO_WORKSPACE", "1")
    monkeypatch.setenv("GENI_STUDIO_TARGET_ROOT", str(tmp_path))
    monkeypatch.setenv("GENI_STUDIO_BACKEND", "stub")
    from geni_studio.config.context import build_run_context

    def wrapped(*args, **kwargs):
        ctx = build_run_context(*args, **kwargs)
        ctx.merged["workflow"] = {**(ctx.merged.get("workflow") or {}), "profile_id": "spec_kit"}
        return ctx

    monkeypatch.setattr("geni_studio.config.context.build_run_context", wrapped)
    service = GraphRunService(graph)
    st = service.start(human_request="加一个问候功能")
    worktree = Path(st.values["workspace_path"])
    assert worktree != tmp_path.resolve()
    (worktree / "hello.txt").write_text("你好\n", encoding="utf-8")
    for _ in range(10):
        if st.phase != "awaiting_human":
            break
        st = service.submit_hitl(st.thread_id, gate_decision="approved")
    assert st.phase == "completed"
    assert (tmp_path / "hello.txt").read_text(encoding="utf-8") == "你好\n"
    assert "并合并到" in str(st.values.get("land_record") or "")


def test_current_branch_activity_does_not_commit_early(monkeypatch):
    from geni_studio.workflows.executable import _activity

    seen: dict[str, str] = {}

    def fake(**kwargs):
        seen["prompt"] = kwargs["user_prompt"]
        return "ok"

    monkeypatch.setattr("geni_studio.backends.runner.invoke_role", fake)
    node = {
        "id": "change_code",
        "name": "改代码",
        "role": "developer",
        "inputs": [],
        "outputs": ["code_change"],
        "on_current_branch": True,
    }
    _activity(node)({"human_request": "改一处"})
    assert "不要执行 git commit" in seen["prompt"]


def test_sqlite_checkpoint_resumes(tmp_path, monkeypatch):
    monkeypatch.setenv("GENI_STUDIO_WORKSPACE", "0")
    db = tmp_path / "checkpoints.sqlite"
    svc = GraphRunService(compile_graph(sqlite_checkpointer(db)))
    st = svc.start(human_request="persist", scenario_key="npu_operator")
    again = GraphRunService(compile_graph(sqlite_checkpointer(db))).status(st.thread_id)
    assert again.phase == "awaiting_human"
    assert again.thread_id == st.thread_id


def test_cursor_defaults_to_auto_route_and_worktree_tools(tmp_path, monkeypatch):
    pytest.importorskip("cursor_sdk")
    monkeypatch.setenv("CURSOR_API_KEY", "test-key")
    monkeypatch.setenv("GENI_STUDIO_CURSOR_VERIFY", "0")
    monkeypatch.delenv("GENI_STUDIO_CURSOR_MODEL", raising=False)
    captured: dict = {}

    class _Run:
        def text(self) -> str:
            return "ok"

    class _Agent:
        def send(self, prompt: str, options=None):
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
