"""人在停点上的历次决定可以回看：当时的待决内容、人的选择与意见。"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

from geni_studio.hitl.decision_log import node_decisions, record_decision
from geni_studio.hitl.service import GraphRunService
from geni_studio.workflows.default import compile_graph, graph


def test_gate_decisions_are_recorded_and_served_per_gate(tmp_path, monkeypatch) -> None:
    from geni_studio.web.app import app, run_service

    monkeypatch.setattr("geni_studio.hitl.conversation.factory_root", lambda: tmp_path)
    svc = run_service()
    st = svc.start(human_request="回看决策", scenario_key="npu_operator")
    gate = st.awaiting_human.gate_id
    summary = st.awaiting_human.summary
    after = svc.submit_hitl(st.thread_id, gate_decision="approved", human_reply="范围可以")
    second = after.awaiting_human.gate_id
    assert second and second != gate
    svc.submit_hitl(st.thread_id, gate_decision="rejected", human_reply="架构要重做")

    client = TestClient(app)
    first = client.get(f"/api/runs/{st.thread_id}/conversations/{gate}").json()["decisions"]
    assert len(first) == 1
    assert first[0]["kind"] == "gate"
    assert first[0]["decision"] == "approved"
    assert first[0]["reply"] == "范围可以"
    assert first[0]["summary"] == summary
    assert first[0]["channel"] == "web"
    assert isinstance(first[0]["review"], list)
    later = client.get(f"/api/runs/{st.thread_id}/conversations/{second}").json()["decisions"]
    assert [(d["decision"], d["reply"]) for d in later] == [("rejected", "架构要重做")]
    activity = client.get(f"/api/runs/{st.thread_id}/conversations/project_manager_draft").json()
    assert activity["decisions"] == []


def test_clarification_reply_is_recorded_on_the_asking_cell(tmp_path, monkeypatch) -> None:
    def fake_invoke(*, role_name: str, user_prompt: str, stub_note: str) -> str:
        if role_name == "project_manager":
            return "## 需求草案\n\n## 待澄清\n- 交付范围？\n"
        return f"[stub:{role_name}] {stub_note}"

    monkeypatch.setattr("geni_studio.hitl.conversation.factory_root", lambda: tmp_path)
    monkeypatch.setattr("geni_studio.backends.runner.invoke_role", fake_invoke)
    svc = GraphRunService(graph)
    st = svc.start(human_request="澄清", scenario_key="npu_operator")
    assert st.awaiting_human.kind == "pm_clarification"
    svc.submit_hitl(st.thread_id, human_reply="仅 Mul 算子", channel="feishu", actor="ou_pm")

    values = svc.status(st.thread_id).values
    found = node_decisions(st.thread_id, "project_manager_draft", values)
    assert [(d["kind"], d["decision"], d["reply"], d["actor"]) for d in found] == [
        ("pm_clarification", "replied", "仅 Mul 算子", "ou_pm"),
    ]
    assert found[0]["questions"] == ["交付范围？"]


def _custom_root(tmp_path: Path) -> None:
    (tmp_path / "scenarios" / "demo").mkdir(parents=True)
    (tmp_path / "scenarios" / "demo" / "scenario.yaml").write_text("scenario_key: demo\ntitle: 演示\n", encoding="utf-8")
    (tmp_path / "projects" / "bound").mkdir(parents=True)
    (tmp_path / "projects" / "bound" / "project.yaml").write_text(
        "project_id: bound\ntitle: 绑定\nscenario_key: demo\nworkflow:\n  profile_id: sample\n",
        encoding="utf-8",
    )
    for role, inputs, outputs in (
        ("project_manager", "human_request", "requirement_spec"),
        ("developer", "requirement_spec", "code_change"),
    ):
        (tmp_path / "roles" / role).mkdir(parents=True)
        (tmp_path / "roles" / role / "role.md").write_text(
            f"---\nname: {role}\ntitle: {role}\ninputs: [{inputs}]\noutputs: [{outputs}]\n---\n",
            encoding="utf-8",
        )
    (tmp_path / "workflows" / "sample").mkdir(parents=True)
    (tmp_path / "workflows" / "sample" / "workflow.yaml").write_text(
        "workflow_id: sample\ntitle: 示例\nnodes:\n"
        "- {id: start, kind: start, name: 启动, role: human, returns_to: ''}\n"
        "- {id: n1, kind: activity, name: 起草, role: project_manager, returns_to: ''}\n"
        "- {id: n3, kind: activity, name: 开发, role: developer, returns_to: n1, max_loops: 1}\n"
        "- {id: n4, kind: gate, name: 看结果, role: human, returns_to: '', decision: approve}\n"
        "- {id: end, kind: end, name: 结束, role: human, returns_to: ''}\n",
        encoding="utf-8",
    )


def test_escalation_choice_is_recorded_on_the_escalated_cell(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    _custom_root(tmp_path)
    monkeypatch.setattr("geni_studio.config.context.factory_root", lambda: tmp_path)
    monkeypatch.setattr("geni_studio.config.registry.factory_root", lambda: tmp_path)
    monkeypatch.setattr("geni_studio.hitl.conversation.factory_root", lambda: tmp_path)
    monkeypatch.setattr("geni_studio.config.precheck.precheck_scenario_materials", lambda *args, **kwargs: None)
    monkeypatch.setattr("geni_studio.hitl.service.workspace_enabled", lambda: False)

    def fake_invoke(*, role_name: str, user_prompt: str, stub_note: str, model: str | None = None) -> str:
        return "未通过\nSTATUS: fail" if role_name == "developer" else f"[stub:{role_name}] {stub_note}"

    monkeypatch.setattr("geni_studio.backends.runner.invoke_role", fake_invoke)
    svc = GraphRunService(compile_graph(MemorySaver()))
    st = svc.start(human_request="升级", scenario_key="demo", project_id="bound")
    assert st.awaiting_human.kind == "escalation"
    svc.submit_hitl(st.thread_id, escalation_choice="continue")

    values = svc.status(st.thread_id).values
    found = node_decisions(st.thread_id, "n3", values)
    assert [(d["kind"], d["decision"], d["reply"]) for d in found] == [("escalation", "continue", "")]
    assert node_decisions(st.thread_id, "n4", values) == []


def test_older_decisions_fall_back_to_the_baseline_log(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("geni_studio.hitl.conversation.factory_root", lambda: tmp_path)
    log = (
        "[baseline:gate_x] decision=rejected at=2026-11-01T08:00:00Z note='先补测试'\n"
        "[baseline:gate_y] decision=approved at=2026-11-01T09:00:00Z\n"
        "[baseline:gate_x] decision=approved at=2026-11-02T08:00:00Z\n"
    )
    record_decision(
        "mixed", node="gate_x", kind="gate", summary="新记录", review=[], decision="approved",
        reply="", channel="feishu", actor="ou_1",
    )
    path = tmp_path / ".geni_studio" / "runs" / "mixed" / "decisions.jsonl"
    stamp = path.read_text(encoding="utf-8").split('"at": "')[1][:19]
    log += f"[baseline:gate_x] decision=approved at={stamp}Z\n"

    found = node_decisions("mixed", "gate_x", {"baseline_log": log}, reject_label="改代码")
    assert [(d["decision"], d.get("legacy", False), d.get("summary", "")) for d in found] == [
        ("rejected", True, ""),
        ("approved", True, ""),
        ("approved", False, "新记录"),
    ]
    assert found[0]["reply"] == "先补测试"
    assert found[0]["reject_label"] == "改代码"
    only_log = node_decisions("mixed", "gate_y", {"baseline_log": log})
    assert [(d["decision"], d["legacy"]) for d in only_log] == [("approved", True)]
