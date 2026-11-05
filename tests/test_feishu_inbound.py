"""飞书入站、卡片与 PM/升级 HITL 测试。"""

from fastapi.testclient import TestClient

from auto_studio.hitl.feishu_cards import build_gate_interactive_card
from auto_studio.hitl.feishu_inbound import (
    parse_card_action_trigger,
    url_verification_response,
)
from auto_studio.hitl.service import GraphRunService
from auto_studio.web.app import app
from auto_studio.workflows.default import graph


def test_url_verification():
    assert url_verification_response({"challenge": "abc", "type": "url_verification"}) == {
        "challenge": "abc"
    }


def test_parse_card_action():
    event = {
        "type": "card.action.trigger",
        "action_value": '{"thread_id":"t1","gate_decision":"approved"}',
    }
    assert parse_card_action_trigger(event)["thread_id"] == "t1"


def test_gate_card_has_buttons():
    card = build_gate_interactive_card(
        thread_id="tid",
        summary="需求确认",
        gate_id="gate_requirement_confirm",
        web_url="http://127.0.0.1:8765/?thread=tid",
    )
    assert card["schema"] == "2.0"
    body = str(card)
    assert "approved" in body and "rejected" in body


def test_card_action_api_flow():
    client = TestClient(app)
    r = client.post(
        "/api/runs",
        json={"human_request": "feishu card", "scenario_key": "npu_operator"},
    )
    tid = r.json()["thread_id"]
    r2 = client.post(
        "/api/webhooks/feishu/card-action",
        json={"thread_id": tid, "gate_decision": "approved", "human_reply": "ok"},
    )
    assert r2.status_code == 200
    assert r2.json()["awaiting_human"]["gate_id"] == "gate_architecture_review"


def test_pm_clarification_open_and_submit():
    svc = GraphRunService(graph)
    st = svc.start(human_request="clarify", scenario_key="npu_operator")
    tid = st.thread_id
    svc.open_hitl(
        tid,
        kind="pm_clarification",
        questions=["Q1?"],
        summary="请确认范围",
    )
    st2 = svc.status(tid)
    assert st2.phase == "awaiting_human"
    assert st2.awaiting_human is not None
    assert st2.awaiting_human.kind == "pm_clarification"
    svc.submit_hitl(tid, human_reply="范围仅 Mul 算子", channel="web")
    st3 = svc.status(tid)
    assert st3.awaiting_human is None or st3.awaiting_human.kind == "gate"


def test_escalation_pause():
    svc = GraphRunService(graph)
    st = svc.start(human_request="esc", scenario_key="npu_operator")
    tid = st.thread_id
    svc.open_hitl(tid, kind="escalation", summary="预算预警")
    svc.submit_hitl(tid, escalation_choice="pause", channel="web")
    assert "hitl_audit_log" in svc.status(tid).values or "run_record" in svc.status(tid).values
