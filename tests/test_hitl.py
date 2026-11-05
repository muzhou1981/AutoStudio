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


def test_api_unknown_thread_404() -> None:
    client = TestClient(app)
    r = client.get("/api/runs/00000000-0000-0000-0000-000000000099")
    assert r.status_code == 404


def test_hitl_ui_served() -> None:
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    assert "Web HITL" in r.text


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
