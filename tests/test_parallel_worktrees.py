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


_COMPARE = _FLOW.replace("  name: 两路\n", "  name: 两路\n  join: compare\n").replace(
    "name: 确认, role: human, returns_to: '', decision: approve}", "name: 选一路, role: human, returns_to: '', decision: pick}"
)


def _compare_run(tmp_path, monkeypatch):
    target = _setup(tmp_path, monkeypatch)
    (tmp_path / "workflows" / "sample" / "workflow.yaml").write_text(_COMPARE, encoding="utf-8")
    files = {"developer": {"shared.txt": "甲的改法\n"}, "tester": {"shared.txt": "乙的改法\n"}}
    seen: dict[str, str] = {}
    monkeypatch.setattr("geni_studio.backends.runner.invoke_role", _writer(files, seen, {"now": 0, "max": 0}))
    svc = GraphRunService(compile_graph(MemorySaver()))
    st = svc.start(human_request="两路对照", scenario_key="demo", project_id="bound")
    return target, svc, st, seen


def test_compare_keeps_branches_apart_until_one_is_picked(tmp_path, monkeypatch):
    from geni_studio.hitl.conversation import conversation_dir
    from geni_studio.hitl.service import HitlError

    target, svc, st, seen = _compare_run(tmp_path, monkeypatch)
    assert st.awaiting_human is not None and st.awaiting_human.gate_id == "gate"
    worktree = Path(st.values["workspace_path"])
    assert (worktree / "shared.txt").read_text(encoding="utf-8") == "base\n"
    assert Path(seen["developer"]).exists() and Path(seen["tester"]).exists()
    comparison = st.values["extra_artifacts"]["branch_comparison"]
    assert "## 实现甲" in comparison and "## 实现乙" in comparison and "`shared.txt` +1 −1" in comparison
    payload = svc.status_dict(st.thread_id)
    assert payload["awaiting_human"]["pick_options"] == [{"id": "b1", "name": "实现甲"}, {"id": "b2", "name": "实现乙"}]
    with pytest.raises(HitlError, match="要指定采用哪一路"):
        svc.submit_hitl(st.thread_id, gate_decision="approved")
    done = svc.submit_hitl(st.thread_id, gate_decision="approved", branch_choice="b2", human_reply="乙更清楚")
    assert done.phase == "completed"
    assert (worktree / "shared.txt").read_text(encoding="utf-8") == "乙的改法\n"
    assert done.values["test_report"].startswith("[tester]") and "实现甲" not in done.values["test_report"]
    assert not Path(seen["developer"]).exists() and not Path(seen["tester"]).exists()
    kept = conversation_dir(st.thread_id, str(worktree)).parent / "branches" / "both__b1.patch"
    assert "甲的改法" in kept.read_text(encoding="utf-8")
    assert not (kept.parent / "both__b2.patch").exists()
    log = (conversation_dir(st.thread_id, str(worktree)).parent / "decisions.jsonl").read_text(encoding="utf-8")
    assert '"picked": "实现乙"' in log
    assert not any((target / ".geni_studio" / "branches" / st.thread_id).iterdir())


def test_compare_reject_adopts_neither(tmp_path, monkeypatch):
    _target, svc, st, seen = _compare_run(tmp_path, monkeypatch)
    worktree = Path(st.values["workspace_path"])
    done = svc.submit_hitl(st.thread_id, gate_decision="rejected", human_reply="都不行")
    assert done.phase == "rejected"
    assert (worktree / "shared.txt").read_text(encoding="utf-8") == "base\n"
    assert not Path(seen["developer"]).exists() and not Path(seen["tester"]).exists()


def test_compare_needs_a_pick_gate_and_the_other_way_round(tmp_path, monkeypatch):
    from geni_studio.config.context import ConfigError
    from geni_studio.config.workflow_defs import validate_workflow

    _setup(tmp_path, monkeypatch)
    import yaml

    data = yaml.safe_load(_COMPARE)
    lonely = {**data, "nodes": [node for node in data["nodes"] if node["id"] != "gate"]}
    with pytest.raises(ConfigError, match="后面要有一个「择一」决策点"):
        validate_workflow(lonely, root=tmp_path, workflow_id="sample")
    merged = yaml.safe_load(_FLOW)
    merged["nodes"][-2]["decision"] = "pick"
    with pytest.raises(ConfigError, match="前面没有选了对照择一的并行"):
        validate_workflow(merged, root=tmp_path, workflow_id="sample")


def test_pick_gate_card_offers_one_button_per_branch(tmp_path, monkeypatch):
    from geni_studio.hitl.feishu_cards import build_gate_interactive_card
    from geni_studio.hitl.feishu_inbound import parse_card_action_trigger
    from geni_studio.hitl.reading import human_reading

    _target, svc, st, _seen = _compare_run(tmp_path, monkeypatch)
    payload = svc.status_dict(st.thread_id)
    sections = human_reading(payload["awaiting_human"], st.values)
    assert sections[0]["title"] == "两路对照" and "## 实现乙" in sections[0]["body"]
    card = build_gate_interactive_card(
        thread_id=st.thread_id,
        summary="",
        gate_id="gate",
        web_url="http://x",
        node_label="选一路",
        pick_options=payload["awaiting_human"]["pick_options"],
    )
    buttons = [
        column["elements"][0]
        for element in card["body"]["elements"]
        if element.get("tag") == "column_set"
        for column in element["columns"]
    ]
    assert [b["text"]["content"] for b in buttons] == ["采用「实现甲」", "采用「实现乙」", "都不采用"]
    value = buttons[1]["behaviors"][0]["value"]
    assert value["branch_choice"] == "b2" and value["gate_decision"] == "approved"
    action = parse_card_action_trigger({"action": {"value": value}})
    assert action["branch_choice"] == "b2"


def test_gate_reply_carries_attachments_into_the_run(tmp_path, monkeypatch):
    from geni_studio.hitl.attachments import store_upload

    _setup(tmp_path, monkeypatch)
    monkeypatch.setattr("geni_studio.hitl.attachments.factory_root", lambda: tmp_path)
    monkeypatch.setattr("geni_studio.backends.runner.invoke_role", lambda **kw: f"[{kw['role_name']}]")
    svc = GraphRunService(compile_graph(MemorySaver()))
    st = svc.start(human_request="带附件批复", scenario_key="demo", project_id="bound")
    assert st.awaiting_human is not None and st.awaiting_human.gate_id == "gate"
    first = store_upload("说明.md", "补充说明\n".encode())
    second = store_upload("说明.md", "第二份\n".encode())
    done = svc.submit_hitl(
        st.thread_id, gate_decision="approved", human_reply="见附件", attachments=[first["id"], second["id"]]
    )
    names = [Path(item).name for item in done.values["attachments"]]
    assert names == ["说明.md", "说明-2.md"]
    stored = Path(done.values["attachments"][1])
    if not stored.is_absolute():
        stored = Path(st.values["workspace_path"]) / stored
    assert stored.read_text(encoding="utf-8") == "第二份\n"
    from geni_studio.hitl.conversation import conversation_dir

    log = (conversation_dir(st.thread_id, st.values["workspace_path"]).parent / "decisions.jsonl").read_text(encoding="utf-8")
    assert "见附件\\n\\n附件，可直接读取：\\n- " in log and "说明-2.md" in log
