"""写锁按可写目录；并行写入的支路在快照工作树中执行并在汇合时合并（D5）。"""

from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import MemorySaver
from test_subgraph_parallel import _patch, _root

from geni_studio.hitl.service import GraphRunService
from geni_studio.workflows.default import compile_graph
from geni_studio.workspace.context import current_worktree
from geni_studio.workspace.layout import workspace_lock
from geni_studio.workspace.policy import (
    WriteBusy,
    assert_write_available,
    exclusive_write,
)

_FLOW = (
    "workflow_id: sample\ntitle: 并行写\nnodes:\n"
    "- {id: start, kind: start, name: 启动, role: human, returns_to: ''}\n"
    "- id: both\n  kind: parallel\n  name: 两路\n  role: ''\n  returns_to: ''\n  branches:\n"
    "  - id: b1\n    name: 实现甲\n    nodes:\n"
    "    - {id: a1, kind: activity, name: 甲, role: developer, returns_to: ''}\n"
    "  - id: b2\n    name: 实现乙\n    nodes:\n"
    "    - {id: a2, kind: activity, name: 乙, role: tester, returns_to: ''}\n"
    "- {id: gate, kind: gate, name: 确认, role: human, returns_to: '', decision: approve}\n"
    "- {id: end, kind: end, name: 结束, role: human, returns_to: ''}\n"
)


def _setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    _root(tmp_path)
    _patch(monkeypatch, tmp_path)
    for role in ("developer", "tester"):
        path = tmp_path / "roles" / role / "role.md"
        path.write_text(path.read_text(encoding="utf-8").replace("---\n", "---\ncapabilities: [write_files]\n", 1), encoding="utf-8")
    (tmp_path / "workflows" / "sample").mkdir(parents=True)
    (tmp_path / "workflows" / "sample" / "workflow.yaml").write_text(_FLOW, encoding="utf-8")
    target = tmp_path / "target"
    target.mkdir()
    subprocess.run(["git", "init", "-q", str(target)], check=True)
    (target / "shared.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(target), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(target), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"], check=True
    )
    monkeypatch.setattr("geni_studio.hitl.service.workspace_enabled", lambda: True)
    monkeypatch.setenv("GENI_STUDIO_TARGET_ROOT", str(target))
    return target


def _writer(files: dict[str, dict[str, str]], seen: dict[str, str], peak: dict[str, int]):
    lock = threading.Lock()

    def fake_invoke(*, role_name: str, user_prompt: str, stub_note: str, model: str | None = None) -> str:
        with lock:
            peak["now"] += 1
            peak["max"] = max(peak["max"], peak["now"])
        root = Path(current_worktree())
        seen[role_name] = str(root)
        for name, text in files.get(role_name, {}).items():
            (root / name).write_text(text, encoding="utf-8")
        time.sleep(0.05)
        with lock:
            peak["now"] -= 1
        return f"[{role_name}]"

    return fake_invoke


def test_two_runs_of_one_project_hold_separate_locks(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    monkeypatch.setattr("geni_studio.backends.runner.invoke_role", lambda **kw: f"[{kw['role_name']}]")
    svc = GraphRunService(compile_graph(MemorySaver()))
    first = svc.start(human_request="一", scenario_key="demo", project_id="bound")
    first_lock = workspace_lock(first.values["workspace_path"])
    assert first_lock is not None
    with exclusive_write(first_lock[0], owner=first.thread_id, lock_file=first_lock[1]):
        second = svc.start(human_request="二", scenario_key="demo", project_id="bound")
        assert second.phase == "awaiting_human"
        with pytest.raises(WriteBusy):
            assert_write_available(*first_lock)
    repo_lock = workspace_lock(str(first_lock[0]))
    assert repo_lock is not None and repo_lock[1].name == "write.lock"
    assert first_lock[1].is_file()
    svc.delete_run(first.thread_id, confirm_name=first.values["run_name"])
    assert not first_lock[1].exists()


def test_parallel_writers_run_in_snapshots_and_merge_back(tmp_path, monkeypatch):
    target = _setup(tmp_path, monkeypatch)
    seen: dict[str, str] = {}
    peak = {"now": 0, "max": 0}
    files = {"developer": {"a.txt": "甲\n"}, "tester": {"b.txt": "乙\n"}}
    monkeypatch.setattr("geni_studio.backends.runner.invoke_role", _writer(files, seen, peak))
    svc = GraphRunService(compile_graph(MemorySaver()))
    st = svc.start(human_request="并行写", scenario_key="demo", project_id="bound")
    assert st.phase == "awaiting_human"
    assert st.awaiting_human is not None and st.awaiting_human.gate_id == "gate"
    worktree = Path(st.values["workspace_path"])
    assert (worktree / "a.txt").read_text(encoding="utf-8") == "甲\n"
    assert (worktree / "b.txt").read_text(encoding="utf-8") == "乙\n"
    assert seen["developer"] != seen["tester"] != str(worktree)
    assert peak["max"] >= 2
    assert not Path(seen["developer"]).exists()
    assert not any((target / ".geni_studio" / "branches" / st.thread_id).iterdir())


def test_conflicting_branches_escalate_with_markers(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    files = {"developer": {"shared.txt": "甲的改法\n"}, "tester": {"shared.txt": "乙的改法\n"}}
    monkeypatch.setattr("geni_studio.backends.runner.invoke_role", _writer(files, {}, {"now": 0, "max": 0}))
    svc = GraphRunService(compile_graph(MemorySaver()))
    st = svc.start(human_request="冲突", scenario_key="demo", project_id="bound")
    assert st.awaiting_human is not None and st.awaiting_human.kind == "escalation"
    assert "shared.txt" in st.awaiting_human.summary and "冲突" in st.awaiting_human.summary
    worktree = Path(st.values["workspace_path"])
    text = (worktree / "shared.txt").read_text(encoding="utf-8")
    assert "<<<<<<<" in text and "甲的改法" in text and "乙的改法" in text
    (worktree / "shared.txt").write_text("合并后\n", encoding="utf-8")
    resumed = svc.submit_hitl(st.thread_id, escalation_choice="continue")
    assert resumed.awaiting_human is not None and resumed.awaiting_human.gate_id == "gate"
    assert (worktree / "shared.txt").read_text(encoding="utf-8") == "合并后\n"
