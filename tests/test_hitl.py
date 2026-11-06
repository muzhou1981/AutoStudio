"""Web HITL 与 GraphRunService 测试。"""

import pytest
from fastapi.testclient import TestClient

from auto_studio.hitl.service import GraphRunService, HitlError
from auto_studio.web.app import app
from auto_studio.workflows.default import graph


@pytest.fixture
def svc() -> GraphRunService:
    return GraphRunService(graph)


def test_start_pauses_at_requirement_gate(svc: GraphRunService) -> None:
    st = svc.start(human_request="demo", scenario_key="npu_operator")
    assert st.phase == "awaiting_human"
    assert st.awaiting_human is not None
    assert st.awaiting_human.gate_id == "gate_requirement_confirm"


def test_gate_approved_advances_to_next_gate(svc: GraphRunService) -> None:
    st = svc.start(human_request="demo", scenario_key="npu_operator")
    tid = st.thread_id
    st = svc.submit_hitl(tid, gate_decision="approved", human_reply="LGTM")
    assert "gate_requirement_confirm" in (st.values.get("baseline_log") or "")
    assert st.phase == "awaiting_human"
    assert st.awaiting_human is not None
    assert st.awaiting_human.gate_id == "gate_architecture_review"


def test_gate_rejected_ends_run(svc: GraphRunService) -> None:
    st = svc.start(human_request="demo", scenario_key="npu_operator")
    tid = st.thread_id
    st = svc.submit_hitl(tid, gate_decision="rejected", human_reply="scope wrong")
    assert st.phase == "rejected"
    assert st.next_nodes == ()
    assert st.values.get("last_gate_decision") == "rejected"


def test_submit_without_awaiting_raises(svc: GraphRunService) -> None:
    st = svc.start(human_request="x", scenario_key="npu_operator")
    svc.submit_hitl(st.thread_id, gate_decision="rejected")
    with pytest.raises(HitlError, match="awaiting_human"):
        svc.submit_hitl(st.thread_id, gate_decision="approved")


def test_api_start_and_hitl_flow() -> None:
    client = TestClient(app)
    r = client.post(
        "/api/runs",
        json={"human_request": "api test", "scenario_key": "npu_operator"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["phase"] == "awaiting_human"
    tid = data["thread_id"]

    r2 = client.post(
        f"/api/runs/{tid}/hitl",
        json={"gate_decision": "approved", "human_reply": "ok"},
    )
    assert r2.status_code == 200
    assert r2.json()["awaiting_human"]["gate_id"] == "gate_architecture_review"

    r3 = client.get(f"/api/runs/{tid}")
    assert r3.status_code == 200


def test_stop_at_gate_ends_the_round(svc: GraphRunService) -> None:
    st = svc.start(human_request="stop", scenario_key="npu_operator")
    st = svc.stop(st.thread_id)
    assert st.phase == "stopped"
    assert st.next_nodes == ()
    assert st.values.get("stopped_at") == "gate_requirement_confirm"
    assert st.values.get("last_gate_decision") != "rejected"
    with pytest.raises(HitlError, match="awaiting_human"):
        svc.submit_hitl(st.thread_id, gate_decision="approved")


def test_stop_again_stays_stopped(svc: GraphRunService) -> None:
    st = svc.start(human_request="stop", scenario_key="npu_operator")
    svc.stop(st.thread_id)
    st = svc.stop(st.thread_id)
    assert st.phase == "stopped"


def test_stop_finished_run_raises(svc: GraphRunService) -> None:
    st = svc.start(human_request="stop", scenario_key="npu_operator")
    svc.submit_hitl(st.thread_id, gate_decision="rejected")
    with pytest.raises(HitlError, match="已结束"):
        svc.stop(st.thread_id)


def test_stop_requested_before_start_skips_nodes(svc: GraphRunService) -> None:
    from auto_studio.hitl.control import request_stop

    tid = "stop-before-start"
    request_stop(tid)
    st = svc.start(human_request="stop", scenario_key="npu_operator", thread_id=tid)
    assert st.phase == "stopped"
    assert not st.values.get("requirement_spec")


def test_stop_during_first_node_does_not_reach_the_gate(svc: GraphRunService, monkeypatch: pytest.MonkeyPatch) -> None:
    from auto_studio.backends.runner import invoke_role
    from auto_studio.hitl.control import current_thread_id, request_stop

    def wrapped(**kwargs):
        request_stop(current_thread_id())
        return invoke_role(**kwargs)

    monkeypatch.setattr("auto_studio.backends.runner.invoke_role", wrapped)
    st = svc.start(human_request="stop", scenario_key="npu_operator")
    assert st.phase == "stopped"
    assert st.next_nodes == ()
    assert st.awaiting_human is None
    assert not st.values.get("testability_review")


def test_api_stop_run() -> None:
    client = TestClient(app)
    started = client.post(
        "/api/runs",
        json={"human_request": "api stop", "scenario_key": "npu_operator"},
    )
    assert started.status_code == 200
    tid = started.json()["thread_id"]
    stopped = client.post(f"/api/runs/{tid}/stop")
    assert stopped.status_code == 200
    body = stopped.json()
    assert body["phase"] == "stopped"
    assert body["rail"]["current"] == "gate_requirement_confirm"
    again = client.post(f"/api/runs/{tid}/stop")
    assert again.status_code == 200
    assert again.json()["phase"] == "stopped"


def test_api_stop_unknown_is_pending() -> None:
    client = TestClient(app)
    pending = client.post("/api/runs/pending-stop-id/stop")
    assert pending.status_code == 200
    assert pending.json()["stop_requested"] is True


def test_pause_during_first_node_keeps_the_round(svc: GraphRunService, monkeypatch: pytest.MonkeyPatch) -> None:
    from auto_studio.backends.runner import invoke_role
    from auto_studio.hitl.control import current_thread_id, request_pause

    once = {"done": False}

    def wrapped(**kwargs):
        if not once["done"]:
            once["done"] = True
            request_pause(current_thread_id())
        return invoke_role(**kwargs)

    monkeypatch.setattr("auto_studio.backends.runner.invoke_role", wrapped)
    st = svc.start(human_request="pause", scenario_key="npu_operator")
    assert st.phase == "paused"
    assert st.next_nodes == ("project_manager_draft",)
    assert st.awaiting_human is None
    assert not st.values.get("requirement_spec")
    assert st.values.get("run_stopped") is not True
    rail = {cell["id"]: cell["state"] for cell in svc.status_dict(st.thread_id)["rail"]["cells"]}
    assert rail["project_manager_draft"] == "paused"
    resumed = svc.resume(st.thread_id)
    assert resumed.phase == "awaiting_human"
    assert resumed.awaiting_human is not None
    assert resumed.awaiting_human.gate_id == "gate_requirement_confirm"
    assert resumed.values.get("requirement_spec")


def test_pause_after_first_node_does_not_redo_it(svc: GraphRunService, monkeypatch: pytest.MonkeyPatch) -> None:
    from auto_studio.backends.runner import invoke_role
    from auto_studio.hitl.control import RunPaused, current_thread_id, request_pause

    once = {"done": False}

    def wrapped(**kwargs):
        if kwargs.get("role_name") == "tester" and not once["done"]:
            once["done"] = True
            request_pause(current_thread_id())
            raise RunPaused("本轮已暂停")
        return invoke_role(**kwargs)

    monkeypatch.setattr("auto_studio.backends.runner.invoke_role", wrapped)
    st = svc.start(human_request="pause later", scenario_key="npu_operator")
    spec = st.values.get("requirement_spec")
    assert st.phase == "paused"
    assert spec
    assert st.next_nodes == ("tester_testability",)
    assert not st.values.get("testability_review")
    resumed = svc.resume(st.thread_id)
    assert resumed.phase == "awaiting_human"
    assert resumed.values.get("requirement_spec") == spec
    assert resumed.values.get("testability_review")


def test_stop_from_paused_ends_the_round(svc: GraphRunService, monkeypatch: pytest.MonkeyPatch) -> None:
    from auto_studio.backends.runner import invoke_role
    from auto_studio.hitl.control import current_thread_id, request_pause

    def wrapped(**kwargs):
        request_pause(current_thread_id())
        return invoke_role(**kwargs)

    monkeypatch.setattr("auto_studio.backends.runner.invoke_role", wrapped)
    st = svc.start(human_request="pause then stop", scenario_key="npu_operator")
    assert st.phase == "paused"
    stopped = svc.stop(st.thread_id)
    assert stopped.phase == "stopped"
    assert stopped.next_nodes == ()
    with pytest.raises(HitlError):
        svc.resume(st.thread_id)


def test_pause_while_waiting_is_rejected(svc: GraphRunService) -> None:
    st = svc.start(human_request="gate", scenario_key="npu_operator")
    with pytest.raises(HitlError):
        svc.pause(st.thread_id)
    assert svc.status(st.thread_id).phase == "awaiting_human"


def test_api_pause_and_resume() -> None:
    client = TestClient(app)
    started = client.post(
        "/api/runs",
        json={"human_request": "api pause", "scenario_key": "npu_operator"},
    )
    tid = started.json()["thread_id"]
    paused = client.post(f"/api/runs/{tid}/pause")
    assert paused.status_code == 409
    missing = client.post("/api/runs/00000000-0000-0000-0000-000000000099/pause")
    assert missing.status_code == 404


def test_api_unknown_thread_404() -> None:
    client = TestClient(app)
    r = client.get("/api/runs/00000000-0000-0000-0000-000000000099")
    assert r.status_code == 404


def test_hitl_ui_served() -> None:
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    assert "Web HITL" in r.text
    assert ">暂停</wa-button>" in r.text
    assert "暂停本轮" not in r.text
    assert "停止本轮" not in r.text
    assert "启动本轮" not in r.text


def test_api_escalation_submit() -> None:
    client = TestClient(app)
    svc = GraphRunService(graph)
    st = svc.start(human_request="esc", scenario_key="npu_operator")
    tid = st.thread_id
    svc.open_hitl(tid, kind="escalation", summary="预算预警")
    r = client.post(
        f"/api/runs/{tid}/hitl",
        json={"escalation_choice": "pause", "human_reply": "先停", "channel": "web"},
    )
    assert r.status_code == 200


def test_run_record_from_hitl_audit(svc: GraphRunService) -> None:
    st = svc.start(human_request="audit", scenario_key="npu_operator")
    tid = st.thread_id
    for _ in range(12):
        st = svc.status(tid)
        if st.phase == "completed":
            break
        if (
            st.phase == "awaiting_human"
            and st.awaiting_human
            and st.awaiting_human.kind == "gate"
        ):
            svc.submit_hitl(tid, gate_decision="approved", channel="web")
            continue
        if st.phase == "running":
            svc._graph.invoke(None, svc._config(tid))
            continue
        break
    st = svc.status(tid)
    assert st.phase == "completed"
    assert "hitl" in (st.values.get("run_record") or "").lower()
    assert "backend=stub" in (st.values.get("cost_ledger") or "")
