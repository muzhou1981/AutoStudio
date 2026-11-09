"""节点失败或服务中断后可以续跑，暂停后的继续保持原样。"""

import pytest

from geni_studio.config.workflow_defs import list_role_lanes
from geni_studio.hitl.service import GraphRunService, HitlError
from geni_studio.workflows.default import graph


@pytest.fixture
def svc() -> GraphRunService:
    return GraphRunService(graph)


def test_compliance_role_is_available() -> None:
    found = next(item for item in list_role_lanes() if item["id"] == "compliance")
    assert found["label"] == "合规管理"
    assert "qa_report" in found["inputs"]
    assert found["outputs"] == ["compliance_report"]


def test_node_failure_can_continue_without_redoing_finished_work(
    svc: GraphRunService, monkeypatch: pytest.MonkeyPatch
) -> None:
    from geni_studio.backends.runner import invoke_role

    def wrapped(**kwargs):
        if kwargs.get("role_name") == "tester":
            raise RuntimeError("节点失败")
        return invoke_role(**kwargs)

    monkeypatch.setattr("geni_studio.backends.runner.invoke_role", wrapped)
    with pytest.raises(RuntimeError, match="节点失败"):
        svc.start(human_request="中断", scenario_key="npu_operator", thread_id="interrupt-node")
    failed = svc.status("interrupt-node")
    assert failed.phase == "interrupted"
    spec = failed.values.get("requirement_spec")
    assert spec
    assert not failed.values.get("testability_review")
    rail = {cell["id"]: cell["state"] for cell in svc.status_dict("interrupt-node")["rail"]["cells"]}
    assert rail["project_manager_draft"] == "done"
    assert rail["tester_testability"] == "interrupted"

    monkeypatch.setattr("geni_studio.backends.runner.invoke_role", invoke_role)
    continued = svc.continue_interrupted("interrupt-node")
    assert continued.phase == "awaiting_human"
    assert continued.values.get("requirement_spec") == spec
    assert continued.values.get("testability_review")
    assert continued.awaiting_human is not None
    assert continued.awaiting_human.gate_id == "gate_requirement_confirm"


def test_running_without_worker_is_interrupted_and_pause_resume_stays(
    svc: GraphRunService, monkeypatch: pytest.MonkeyPatch
) -> None:
    from geni_studio.backends.runner import invoke_role
    from geni_studio.hitl.control import RunPaused, current_thread_id, request_pause

    once = {"done": False}

    def wrapped(**kwargs):
        if kwargs.get("role_name") == "tester" and not once["done"]:
            once["done"] = True
            request_pause(current_thread_id())
            raise RunPaused("本轮已暂停")
        return invoke_role(**kwargs)

    monkeypatch.setattr("geni_studio.backends.runner.invoke_role", wrapped)
    paused = svc.start(human_request="先暂停", scenario_key="npu_operator", thread_id="interrupt-gap")
    assert paused.phase == "paused"
    spec = paused.values.get("requirement_spec")
    assert spec
    with pytest.raises(HitlError, match="不能续跑"):
        svc.continue_interrupted("interrupt-gap")

    svc._bound("interrupt-gap").update_state(
        svc._config("interrupt-gap"),
        {"run_paused": False, "paused_at": ""},
    )
    assert svc.status("interrupt-gap").phase == "running"
    observed = svc.status_dict("interrupt-gap")
    assert observed["phase"] == "interrupted"
    assert observed["rail"]["current"] == "tester_testability"

    monkeypatch.setattr("geni_studio.backends.runner.invoke_role", invoke_role)
    continued = svc.continue_interrupted("interrupt-gap")
    assert continued.phase == "awaiting_human"
    assert continued.values.get("requirement_spec") == spec
    assert continued.values.get("testability_review")
