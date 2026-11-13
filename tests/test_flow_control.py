"""流程控制的状态转换。

阶段：未启动、运行中、等待人工、已暂停、已完成、已驳回、已停止。

允许的转换：

- 未启动 → 启动 → 等待人工（桩后端停在需求确认）
- 运行中 → 暂停 → 已暂停；再按暂停仍是已暂停
- 已暂停 → 继续 → 等待人工，已完成的节点不重做
- 已暂停 → 停止 → 已停止；已停止不能继续
- 等待人工 → 停止 → 已停止；再停止仍是已停止
- 等待人工 → 驳回 → 已驳回
- 等待人工 → 逐关批准 → 已完成，“结束”成为最终状态

拒绝的转换：

- 等待人工、已暂停以外的阶段不能暂停
- 不是已暂停不能继续
- 已完成、已驳回不能停止
- 已停止、已暂停不能提交关卡批复
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from geni_studio.hitl.rail import build_rail
from geni_studio.hitl.service import GraphRunService, HitlError
from geni_studio.web.app import app
from geni_studio.workflows.default import graph


@pytest.fixture
def svc() -> GraphRunService:
    return GraphRunService(graph)


def _cells(svc: GraphRunService, thread_id: str) -> tuple[dict, dict[str, str]]:
    data = svc.status_dict(thread_id)
    return data, {cell["id"]: cell["state"] for cell in data["rail"]["cells"]}


def _pause_before(monkeypatch: pytest.MonkeyPatch, role_name: str) -> None:
    from geni_studio.backends.runner import invoke_role
    from geni_studio.hitl.control import RunPaused, current_thread_id, request_pause

    once = {"done": False}

    def wrapped(**kwargs):
        if kwargs.get("role_name") == role_name and not once["done"]:
            once["done"] = True
            request_pause(current_thread_id())
            raise RunPaused("本轮已暂停")
        return invoke_role(**kwargs)

    monkeypatch.setattr("geni_studio.backends.runner.invoke_role", wrapped)


def _drive_to_completed(svc: GraphRunService, thread_id: str):
    for _ in range(12):
        st = svc.status(thread_id)
        if st.phase == "completed":
            return st
        if st.phase == "awaiting_human" and st.awaiting_human and st.awaiting_human.kind == "gate":
            svc.submit_hitl(thread_id, gate_decision="approved")
            continue
        break
    return svc.status(thread_id)


def test_idle_current_cell_is_start():
    rail = build_rail(phase="idle", next_nodes=[], awaiting=None, skip_nodes=set())
    states = {cell["id"]: cell["state"] for cell in rail["cells"]}
    assert rail["current"] == "run_start"
    assert states["run_start"] == "initial"
    assert states["project_manager_draft"] == "pending"
    assert states["run_end"] == "pending"


def test_start_stops_at_requirement_gate(svc: GraphRunService) -> None:
    st = svc.start(human_request="启动", scenario_key="npu_operator")
    data, states = _cells(svc, st.thread_id)
    assert st.phase == "awaiting_human"
    assert st.awaiting_human is not None
    assert st.awaiting_human.gate_id == "gate_requirement_confirm"
    assert data["rail"]["current"] == "gate_requirement_confirm"
    assert states["run_start"] == "done"
    assert states["project_manager_draft"] == "done"
    assert states["gate_requirement_confirm"] == "waiting"
    assert states["run_end"] == "pending"


def test_pause_while_running_then_pause_again_stays(svc: GraphRunService, monkeypatch: pytest.MonkeyPatch) -> None:
    _pause_before(monkeypatch, "project_manager")
    st = svc.start(human_request="暂停", scenario_key="npu_operator")
    assert st.phase == "paused"
    assert st.next_nodes == ("project_manager_draft",)
    data, states = _cells(svc, st.thread_id)
    assert data["rail"]["current"] == "project_manager_draft"
    assert states["run_start"] == "done"
    assert states["project_manager_draft"] == "paused"
    assert states["run_end"] == "pending"
    again = svc.pause(st.thread_id)
    assert again.phase == "paused"
    assert again.next_nodes == ("project_manager_draft",)


def test_resume_from_pause_does_not_redo_finished_nodes(
    svc: GraphRunService, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pause_before(monkeypatch, "tester")
    st = svc.start(human_request="继续", scenario_key="npu_operator")
    spec = st.values.get("requirement_spec")
    assert st.phase == "paused"
    assert st.next_nodes == ("tester_testability",)
    assert spec
    resumed = svc.resume(st.thread_id)
    assert resumed.phase == "awaiting_human"
    assert resumed.awaiting_human is not None
    assert resumed.awaiting_human.gate_id == "gate_requirement_confirm"
    assert resumed.values.get("requirement_spec") == spec
    assert resumed.values.get("testability_review")
    _, states = _cells(svc, st.thread_id)
    assert states["run_start"] == "done"
    assert states["tester_testability"] == "done"
    assert states["gate_requirement_confirm"] == "waiting"


def test_stop_from_paused_cannot_resume(svc: GraphRunService, monkeypatch: pytest.MonkeyPatch) -> None:
    _pause_before(monkeypatch, "project_manager")
    st = svc.start(human_request="暂停后停止", scenario_key="npu_operator")
    assert st.phase == "paused"
    stopped = svc.stop(st.thread_id)
    assert stopped.phase == "stopped"
    assert stopped.next_nodes == ()
    _, states = _cells(svc, st.thread_id)
    assert states["project_manager_draft"] == "stopped"
    assert states["run_end"] == "pending"
    with pytest.raises(HitlError):
        svc.resume(st.thread_id)
    with pytest.raises(HitlError):
        svc.pause(st.thread_id)
    assert svc.stop(st.thread_id).phase == "stopped"


def test_waiting_rejects_pause_and_resume_then_stop_ends(svc: GraphRunService) -> None:
    st = svc.start(human_request="等待后停止", scenario_key="npu_operator")
    assert st.phase == "awaiting_human"
    with pytest.raises(HitlError):
        svc.pause(st.thread_id)
    with pytest.raises(HitlError):
        svc.resume(st.thread_id)
    assert svc.status(st.thread_id).phase == "awaiting_human"
    stopped = svc.stop(st.thread_id)
    assert stopped.phase == "stopped"
    assert stopped.values.get("stopped_at") == "gate_requirement_confirm"
    _, states = _cells(svc, st.thread_id)
    assert states["gate_requirement_confirm"] == "stopped"
    assert states["run_start"] == "done"
    assert states["run_end"] == "pending"
    with pytest.raises(HitlError):
        svc.submit_hitl(st.thread_id, gate_decision="approved")
    assert svc.stop(st.thread_id).phase == "stopped"


def test_reject_gate_blocks_further_control(svc: GraphRunService) -> None:
    st = svc.start(human_request="驳回", scenario_key="npu_operator")
    rejected = svc.submit_hitl(st.thread_id, gate_decision="rejected", human_reply="不行")
    assert rejected.phase == "rejected"
    assert rejected.next_nodes == ()
    _, states = _cells(svc, st.thread_id)
    assert states["gate_requirement_confirm"] == "waiting"
    assert states["run_end"] == "pending"
    with pytest.raises(HitlError):
        svc.pause(st.thread_id)
    with pytest.raises(HitlError):
        svc.resume(st.thread_id)
    with pytest.raises(HitlError):
        svc.stop(st.thread_id)
    with pytest.raises(HitlError):
        svc.submit_hitl(st.thread_id, gate_decision="approved")
    assert svc.status(st.thread_id).phase == "rejected"


def test_approve_until_completed_then_controls_close(svc: GraphRunService) -> None:
    st = svc.start(human_request="走完", scenario_key="npu_operator")
    done = _drive_to_completed(svc, st.thread_id)
    assert done.phase == "completed"
    data, states = _cells(svc, st.thread_id)
    assert data["rail"]["current"] == "run_end"
    assert states["run_start"] == "done"
    assert states["process_owner_retro"] == "done"
    assert states["run_end"] == "finished"
    with pytest.raises(HitlError):
        svc.pause(st.thread_id)
    with pytest.raises(HitlError):
        svc.resume(st.thread_id)
    with pytest.raises(HitlError):
        svc.stop(st.thread_id)
    assert svc.status(st.thread_id).phase == "completed"


def test_http_control_from_waiting_to_stopped() -> None:
    client = TestClient(app)
    started = client.post(
        "/api/runs",
        json={"human_request": "接口控制", "scenario_key": "npu_operator"},
    )
    assert started.status_code == 200
    body = started.json()
    tid = body["thread_id"]
    assert body["phase"] == "awaiting_human"
    assert client.post(f"/api/runs/{tid}/pause").status_code == 409
    assert client.post(f"/api/runs/{tid}/resume").status_code == 409
    stopped = client.post(f"/api/runs/{tid}/stop")
    assert stopped.status_code == 200
    stopped_body = stopped.json()
    assert stopped_body["phase"] == "stopped"
    states = {cell["id"]: cell["state"] for cell in stopped_body["rail"]["cells"]}
    assert stopped_body["rail"]["current"] == "gate_requirement_confirm"
    assert states["run_start"] == "done"
    assert states["gate_requirement_confirm"] == "stopped"
    assert states["run_end"] == "pending"
    assert client.post(f"/api/runs/{tid}/resume").status_code == 409
    assert client.post(f"/api/runs/{tid}/pause").status_code == 409
    again = client.post(f"/api/runs/{tid}/stop")
    assert again.status_code == 200
    assert again.json()["phase"] == "stopped"
