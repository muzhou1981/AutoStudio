"""项目右栏概览：流程、工作区、最近的 Run 与代码尚未回到项目目录的 Run。"""

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from geni_studio.web.app import app
from geni_studio.workspace.pending import current_branch, run_leftover


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")
    _git(repo, "branch", "geni-studio/t-merged")
    _git(repo, "worktree", "add", "-q", "-b", "geni-studio/t-ahead", str(repo / ".geni_studio/worktrees/t-ahead"))
    ahead = repo / ".geni_studio/worktrees/t-ahead"
    (ahead / "b.txt").write_text("b\n", encoding="utf-8")
    _git(ahead, "add", "-A")
    _git(ahead, "commit", "-q", "-m", "work")
    _git(repo, "worktree", "add", "-q", "-b", "geni-studio/t-dirty", str(repo / ".geni_studio/worktrees/t-dirty"))
    (repo / ".geni_studio/worktrees/t-dirty/c.txt").write_text("c\n", encoding="utf-8")
    return repo


def test_run_leftover_reports_unmerged_and_dirty_runs(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    assert current_branch(repo) == "main"
    assert run_leftover(repo, "t-merged") == ""
    assert run_leftover(repo, "t-missing") == ""
    assert run_leftover(repo, "t-ahead") == "本轮分支有 1 个提交未合入 main"
    assert run_leftover(repo, "t-dirty") == "工作树里有未提交的改动"
    assert current_branch(tmp_path) == ""


def test_project_overview_lists_flow_workspace_and_pending_runs(tmp_path: Path, monkeypatch) -> None:
    repo = _repo(tmp_path)
    runs = [
        {"thread_id": "t-busy", "run_name": "busy", "phase": "awaiting_human", "updated_at": 5.0},
        {"thread_id": "t-ahead", "run_name": "ahead", "phase": "completed", "updated_at": 4.0},
        {"thread_id": "t-dirty", "run_name": "dirty", "phase": "stopped", "updated_at": 3.0},
        {"thread_id": "t-merged", "run_name": "merged", "phase": "completed", "updated_at": 2.0},
    ]

    class _Runs:
        def list_runs(self, *, project_id: str = "", phase: str = "") -> list[dict]:
            return [dict(run, project_id=project_id) for run in runs]

    client = TestClient(app)
    assert client.post("/api/config/projects", json={"title": "ov", "project_id": "ov-test"}).status_code == 200
    try:
        saved = client.put(
            "/api/config/projects/ov-test/form",
            json={"title": "ov", "profile_id": "spec_kit", "workspace": str(repo)},
        )
        assert saved.status_code == 200, saved.text
        monkeypatch.setattr("geni_studio.web.app.run_service", lambda: _Runs())
        body = client.get("/api/config/projects/ov-test/overview").json()
        assert body["flow"]["workflow_id"] == "spec_kit" and body["flow"]["exists"] is True
        assert body["flow"]["workspace"] == ""
        assert body["workspace"] == {"configured": str(repo), "path": str(repo), "exists": True, "branch": "main"}
        assert body["run_count"] == 4 and body["unfinished"] == 1
        assert [run["run_name"] for run in body["runs"]] == ["busy", "ahead", "dirty", "merged"]
        assert {run["run_name"]: run["reason"] for run in body["pending"]} == {
            "busy": "未结束",
            "ahead": "本轮分支有 1 个提交未合入 main",
            "dirty": "工作树里有未提交的改动",
        }
    finally:
        monkeypatch.undo()
        client.delete("/api/config/projects/ov-test")
    assert client.get("/api/config/projects/missing-project/overview").status_code == 404
