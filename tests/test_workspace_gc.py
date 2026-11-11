"""删除运行时回收工作树；`geni-studio gc` 回收孤立工作树、运行目录与已合入分支。"""

from __future__ import annotations

import os
import subprocess

from langgraph.checkpoint.memory import MemorySaver

from geni_studio.hitl.service import GraphRunService
from geni_studio.workflows.default import compile_graph
from geni_studio.workspace.gc import collect_garbage


def _branches(repo) -> set[str]:
    out = subprocess.check_output(
        ["git", "-C", os.fspath(repo), "for-each-ref", "--format=%(refname:short)", "refs/heads/geni-studio/"],
        text=True,
    )
    return set(out.split())


def _service(tmp_path, monkeypatch) -> GraphRunService:
    monkeypatch.setenv("GENI_STUDIO_WORKSPACE", "1")
    monkeypatch.setenv("GENI_STUDIO_TARGET_ROOT", str(tmp_path))
    return GraphRunService(compile_graph(checkpointer=MemorySaver()))


def test_delete_run_removes_its_worktree_and_run_dir(tmp_path, monkeypatch):
    svc = _service(tmp_path, monkeypatch)
    st = svc.start(human_request="回收", scenario_key="npu_operator", run_name="待回收")
    worktree = st.values["workspace_path"]
    run_dir = tmp_path / ".geni_studio" / "runs" / st.thread_id
    assert os.path.isdir(worktree) and run_dir.is_dir()

    cleanup = svc.delete_run(st.thread_id, confirm_name="待回收")
    assert not os.path.exists(worktree)
    assert not run_dir.exists()
    assert f"geni-studio/{st.thread_id}" not in _branches(tmp_path)
    assert any("移除工作树" in line for line in cleanup)


def test_unmerged_branch_is_kept_on_delete(tmp_path, monkeypatch):
    svc = _service(tmp_path, monkeypatch)
    st = svc.start(human_request="保留分支", scenario_key="npu_operator", run_name="有提交")
    worktree = st.values["workspace_path"]
    (open(os.path.join(worktree, "work.txt"), "w", encoding="utf-8")).close()
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", "-C", worktree, "add", "work.txt"], check=True)
    subprocess.run(["git", "-C", worktree, "commit", "-qm", "work"], check=True, env=env)

    cleanup = svc.delete_run(st.thread_id, confirm_name="有提交")
    assert not os.path.exists(worktree)
    assert f"geni-studio/{st.thread_id}" in _branches(tmp_path)
    assert any("保留未合入分支" in line for line in cleanup)


def test_gc_collects_only_orphans(tmp_path, monkeypatch):
    svc = _service(tmp_path, monkeypatch)
    live = svc.start(human_request="现存", scenario_key="npu_operator", run_name="现存")
    orphan = svc.start(human_request="孤立", scenario_key="npu_operator", run_name="孤立")
    svc.runtime_store().forget_thread(orphan.thread_id)
    svc._graph.checkpointer.delete_thread(orphan.thread_id)
    alive = svc.live_thread_ids()
    assert live.thread_id in alive and orphan.thread_id not in alive

    preview = collect_garbage(tmp_path, alive, dry_run=True)
    assert preview.removed_worktrees == [orphan.values["workspace_path"]]
    assert os.path.isdir(orphan.values["workspace_path"])

    report = collect_garbage(tmp_path, alive)
    assert not os.path.exists(orphan.values["workspace_path"])
    assert not (tmp_path / ".geni_studio" / "runs" / orphan.thread_id).exists()
    assert f"geni-studio/{orphan.thread_id}" not in _branches(tmp_path)
    assert os.path.isdir(live.values["workspace_path"])
    assert f"geni-studio/{live.thread_id}" in _branches(tmp_path)
    assert not report.errors


def test_gc_command_reports(tmp_path, monkeypatch, capsys):
    from geni_studio.cli import main

    svc = _service(tmp_path, monkeypatch)
    orphan = svc.start(human_request="命令", scenario_key="npu_operator")
    monkeypatch.setattr("geni_studio.hitl.service.GraphRunService.live_thread_ids", lambda self: set())
    monkeypatch.setattr("geni_studio.config.env_loader.apply_env_file", lambda *a, **k: None)
    assert main(["gc", "--repo", str(tmp_path), "--dry-run"]) == 0
    printed = capsys.readouterr().out
    assert "[dry-run] 移除工作树" in printed
    assert os.path.isdir(orphan.values["workspace_path"])
    assert main(["gc", "--repo", str(tmp_path)]) == 0
    assert not os.path.exists(orphan.values["workspace_path"])
