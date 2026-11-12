"""项目选定流程后，当轮按该流程的节点执行。"""

from pathlib import Path

import pytest
from langgraph.checkpoint.memory import MemorySaver

from geni_studio.config.context import ConfigError
from geni_studio.hitl.service import GraphRunService
from geni_studio.workflows.default import compile_graph
from geni_studio.workflows.executable import resolve_executable


def _root(tmp_path: Path) -> None:
    (tmp_path / "scenarios" / "demo").mkdir(parents=True)
    (tmp_path / "scenarios" / "demo" / "scenario.yaml").write_text(
        "scenario_key: demo\ntitle: 演示\n",
        encoding="utf-8",
    )
    (tmp_path / "projects" / "bound").mkdir(parents=True)
    (tmp_path / "projects" / "bound" / "project.yaml").write_text(
        "project_id: bound\ntitle: 绑定\nscenario_key: demo\n"
        "workflow:\n  profile_id: sample\n  limits:\n    max_dev_retries: 2\n",
        encoding="utf-8",
    )
    (tmp_path / "roles" / "project_manager").mkdir(parents=True)
    (tmp_path / "roles" / "project_manager" / "role.md").write_text(
        "---\nname: project_manager\ntitle: 项目经理\ninputs: [human_request]\noutputs: [requirement_spec]\n---\n",
        encoding="utf-8",
    )
    (tmp_path / "roles" / "developer").mkdir(parents=True)
    (tmp_path / "roles" / "developer" / "role.md").write_text(
        "---\nname: developer\ntitle: 程序员\ninputs: [requirement_spec]\noutputs: [code_change]\n---\n",
        encoding="utf-8",
    )
    (tmp_path / "workflows" / "sample").mkdir(parents=True)
    (tmp_path / "workflows" / "sample" / "workflow.yaml").write_text(
        "workflow_id: sample\ntitle: 示例\nnodes:\n"
        "- {id: start, kind: start, name: 启动, role: human, returns_to: ''}\n"
        "- {id: n1, kind: activity, name: 起草, role: project_manager, returns_to: ''}\n"
        "- {id: n2, kind: gate, name: 确认, role: human, returns_to: '', decision: approve}\n"
        "- {id: n3, kind: activity, name: 开发, role: developer, returns_to: n1, max_loops: 2}\n"
        "- {id: end, kind: end, name: 结束, role: human, returns_to: ''}\n",
        encoding="utf-8",
    )


def _patch_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("geni_studio.config.context.factory_root", lambda: tmp_path)
    monkeypatch.setattr("geni_studio.config.registry.factory_root", lambda: tmp_path)
    monkeypatch.setattr("geni_studio.config.precheck.precheck_scenario_materials", lambda *args, **kwargs: None)
    monkeypatch.setattr("geni_studio.hitl.service.workspace_enabled", lambda: False)


def test_gate_rejection_after_escalation_continue_takes_effect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _root(tmp_path)
    (tmp_path / "workflows" / "sample" / "workflow.yaml").write_text(
        "workflow_id: sample\ntitle: 示例\nnodes:\n"
        "- {id: start, kind: start, name: 启动, role: human, returns_to: ''}\n"
        "- {id: n1, kind: activity, name: 起草, role: project_manager, returns_to: ''}\n"
        "- {id: n3, kind: activity, name: 开发, role: developer, returns_to: n1, max_loops: 1}\n"
        "- {id: n4, kind: gate, name: 看结果, role: human, returns_to: '', decision: approve, reject_to: n1}\n"
        "- {id: end, kind: end, name: 结束, role: human, returns_to: ''}\n",
        encoding="utf-8",
    )
    _patch_root(monkeypatch, tmp_path)
    calls = {"project_manager": 0}

    def fake_invoke(*, role_name: str, user_prompt: str, stub_note: str, model: str | None = None) -> str:
        if role_name == "developer":
            return "未通过\nSTATUS: fail"
        calls["project_manager"] += 1
        return f"[stub:{role_name}] {stub_note}"

    monkeypatch.setattr("geni_studio.backends.runner.invoke_role", fake_invoke)
    svc = GraphRunService(compile_graph(MemorySaver()))
    st = svc.start(human_request="做一件事", scenario_key="demo", project_id="bound")
    assert st.awaiting_human is not None and st.awaiting_human.kind == "escalation"
    st = svc.submit_hitl(st.thread_id, escalation_choice="continue")
    assert st.awaiting_human is not None and st.awaiting_human.gate_id == "n4"
    drafted = calls["project_manager"]
    svc._write_values(st.thread_id, {"gate_timeout_note": "超时未批复"})
    assert svc.status(st.thread_id).next_nodes == ("n4",)

    st = svc.submit_hitl(st.thread_id, gate_decision="rejected", human_reply="重写需求")
    assert calls["project_manager"] == drafted + 1
    assert "[baseline:n4] decision=rejected" in st.values["baseline_log"]
    assert st.phase == "awaiting_human"
    assert st.phase != "completed"


def test_missing_decision_refuses_to_start(tmp_path: Path) -> None:
    _root(tmp_path)
    workflow = {
        "workflow_id": "sample",
        "nodes": [
            {"id": "start", "kind": "start", "name": "启动", "role": "human", "returns_to": ""},
            {"id": "n1", "kind": "activity", "name": "起草", "role": "project_manager", "returns_to": ""},
            {"id": "n2", "kind": "gate", "name": "确认", "role": "human", "returns_to": ""},
            {"id": "end", "kind": "end", "name": "结束", "role": "human", "returns_to": ""},
        ],
    }
    with pytest.raises(ConfigError, match="决策点「确认」缺少决定类型"):
        resolve_executable(workflow, root=tmp_path)
    (tmp_path / "roles" / "qa").mkdir(parents=True)
    (tmp_path / "roles" / "qa" / "role.md").write_text(
        "---\nname: qa\ntitle: QA\ninputs: []\noutputs: []\n---\n",
        encoding="utf-8",
    )
    workflow["nodes"][2]["decision"] = "approve"
    workflow["nodes"].insert(
        2,
        {"id": "n9", "kind": "activity", "name": "把关", "role": "qa", "returns_to": ""},
    )
    with pytest.raises(ConfigError, match="活动「把关」缺少产出产物"):
        resolve_executable(workflow, root=tmp_path)
    drafted = {
        "workflow_id": "sample",
        "nodes": [
            {"id": "start", "kind": "start", "name": "启动", "role": "human", "returns_to": ""},
            {
                "id": "n1",
                "kind": "activity",
                "name": "起草",
                "role": "project_manager",
                "returns_to": "",
                "inputs": ["human_request"],
                "outputs": [{"name": "requirement_spec", "source": "link", "template": ""}],
            },
            {"id": "end", "kind": "end", "name": "结束", "role": "human", "returns_to": ""},
        ],
    }
    with pytest.raises(ConfigError, match="输出「requirement_spec」没有模板"):
        resolve_executable(drafted, root=tmp_path)


def test_selected_workflow_runs_activity_gate_and_return(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _root(tmp_path)
    _patch_root(monkeypatch, tmp_path)
    calls = {"developer": 0}

    def fake_invoke(*, role_name: str, user_prompt: str, stub_note: str, model: str | None = None) -> str:
        if role_name == "developer":
            calls["developer"] += 1
            return "未通过\nSTATUS: fail"
        return f"[stub:{role_name}] {stub_note}"

    monkeypatch.setattr("geni_studio.backends.runner.invoke_role", fake_invoke)
    svc = GraphRunService(compile_graph(MemorySaver()))
    started = svc.start(human_request="做一件事", scenario_key="demo", project_id="bound")
    assert started.phase == "awaiting_human"
    assert started.awaiting_human is not None
    assert started.awaiting_human.gate_id == "n2"
    assert "[stub:project_manager] 起草" in started.values["requirement_spec"]
    rail = svc.status_dict(started.thread_id)["rail"]
    assert [cell["id"] for cell in rail["cells"]] == ["start", "n1", "n2", "n3", "end"]
    assert "project_manager_draft" not in {cell["id"] for cell in rail["cells"]}
    by_id = {cell["id"]: cell for cell in rail["cells"]}
    assert by_id["n1"]["role"] == "project_manager"
    assert by_id["n2"]["kind"] == "gate"
    assert by_id["n3"]["role"] == "developer"
    assert rail["current"] == "n2"

    returned = svc.submit_hitl(started.thread_id, gate_decision="approved", human_reply="可以")
    assert returned.phase == "awaiting_human"
    assert returned.awaiting_human is not None
    assert returned.awaiting_human.gate_id == "n2"
    assert returned.values["return_counts"]["n3"] == 1
    assert calls["developer"] == 1

    escalated = svc.submit_hitl(started.thread_id, gate_decision="approved", human_reply="再试")
    assert escalated.phase == "awaiting_human"
    assert escalated.awaiting_human is not None
    assert escalated.awaiting_human.kind == "escalation"
    assert escalated.values["return_counts"]["n3"] == 2
    assert escalated.values["escalated_from"] == "n3"
    assert svc.status_dict(started.thread_id)["rail"]["current"] == "n3"
    assert "STATUS: fail" in escalated.values["code_change"]
