"""飞书入站、卡片与 PM/升级 HITL 测试。"""

import json

from fastapi.testclient import TestClient

from geni_studio.hitl.feishu_cards import (
    build_gate_interactive_card,
    build_pm_clarification_interactive_card,
)
from geni_studio.hitl.feishu_inbound import (
    parse_card_action_trigger,
    url_verification_response,
)
from geni_studio.hitl.service import GraphRunService
from geni_studio.web.app import app
from geni_studio.workflows.default import graph


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
    official = {
        "action": {
            "value": {
                "thread_id": "t1",
                "hitl_action": "gate",
                "gate_decision": "rejected",
            }
        }
    }
    assert parse_card_action_trigger(official)["gate_decision"] == "rejected"


def test_clarification_card_has_reply_input():
    card = build_pm_clarification_interactive_card(
        thread_id="tid",
        summary="请确认范围",
        questions=["预算上限？"],
        web_url="http://127.0.0.1:8765/?thread_id=tid",
    )
    blob = str(card)
    assert "pm_clarification" in blob
    assert "reply" in blob
    assert "thread_id=tid" in blob


def test_gate_card_names_the_reject_target():
    card = build_gate_interactive_card(
        thread_id="tid",
        summary="确认 CCA",
        gate_id="confirm_cca",
        web_url="http://127.0.0.1:8765/?thread_id=tid",
        node_label="确认 CCA",
        reject_label="确认 AOM",
        excerpt="**算子合同**\n先写清接口。",
    )
    body = str(card)
    assert "确认 CCA" in body
    assert "不通过将前往「确认 AOM」" in body
    assert "算子合同" in body


def test_settled_gate_card_has_no_decision_buttons():
    from geni_studio.hitl.feishu_cards import build_settled_gate_card

    card = build_settled_gate_card(node_label="确认 CCA", decision_line="已记录：不通过，前往「确认 AOM」。")
    blob = str(card)
    assert "已记录：不通过" in blob
    assert "gate_decision" not in blob


def test_repeated_gate_card_is_a_toast_not_an_error():
    client = TestClient(app)
    started = client.post(
        "/api/runs",
        json={"human_request": "twice", "scenario_key": "npu_operator"},
    )
    tid = started.json()["thread_id"]
    body = {
        "header": {"event_type": "card.action.trigger"},
        "event": {
            "action": {
                "value": {
                    "thread_id": tid,
                    "hitl_action": "gate",
                    "gate_decision": "approved",
                }
            }
        },
    }
    first = client.post("/api/webhooks/feishu", json=body)
    assert first.status_code == 200
    assert first.json()["card"]["type"] == "raw"
    stopped = client.post(f"/api/runs/{tid}/stop")
    assert stopped.status_code == 200
    second = client.post("/api/webhooks/feishu", json=body)
    assert second.status_code == 200
    assert second.json()["ignored"] == "not_awaiting"


def test_text_approval_does_not_guess_among_several_waiting_runs():
    client = TestClient(app)
    first = client.post(
        "/api/runs",
        json={"human_request": "one", "scenario_key": "npu_operator"},
    ).json()["thread_id"]
    second = client.post(
        "/api/runs",
        json={"human_request": "two", "scenario_key": "npu_operator"},
    ).json()["thread_id"]
    from geni_studio.hitl.feishu_session import register_awaiting_thread

    chat = "oc_multi_wait"
    register_awaiting_thread(thread_id=first, chat_id=chat)
    register_awaiting_thread(thread_id=second, chat_id=chat)
    replied = client.post(
        "/api/webhooks/feishu",
        json={
            "header": {"event_type": "im.message.receive_v1"},
            "event": {
                "message": {
                    "chat_id": chat,
                    "message_type": "text",
                    "content": '{"text":"批准"}',
                },
                "sender": {"sender_id": {"open_id": "ou_multi"}},
            },
        },
    )
    assert replied.status_code == 200
    assert replied.json()["ignored"] == "multiple_awaiting"


def test_start_surfaces_a_feishu_send_failure(monkeypatch):
    from geni_studio.hitl.feishu_notify import NotifyResult

    monkeypatch.setattr(
        "geni_studio.hitl.feishu_notify.notify_awaiting_human_via_lark_cli",
        lambda *_args, **_kwargs: NotifyResult(False, "lark-cli 未就绪。"),
    )
    client = TestClient(app)
    started = client.post(
        "/api/runs",
        json={"human_request": "notice", "scenario_key": "npu_operator"},
    )
    assert started.status_code == 200
    notice = started.json()["feishu_notice"]
    assert notice["sent"] is False
    assert "未就绪" in notice["detail"]


def test_webhook_token_rejects_a_missing_header(monkeypatch):
    monkeypatch.setenv("GENI_STUDIO_FEISHU_WEBHOOK_TOKEN", "secret-token")
    client = TestClient(app)
    denied = client.post(
        "/api/webhooks/feishu",
        json={"header": {"event_type": "im.message.receive_v1"}, "event": {}},
    )
    assert denied.status_code == 401
    allowed = client.post(
        "/api/webhooks/feishu",
        json={"header": {"event_type": "im.message.receive_v1"}, "event": {}},
        headers={"X-Geni-Studio-Webhook-Token": "secret-token"},
    )
    assert allowed.status_code == 200


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
    assert "不通过" in body
    assert "不通过将结束本轮" in body
    assert "需求确认" in body
    assert "待批复 · 需求确认" in body


def test_gate_card_shows_abc_choice_buttons():
    choices = [
        {"id": "A", "label": "只删 placeholder，保留 label", "recommended": True},
        {"id": "B", "label": "placeholder 和 label 都去掉", "recommended": False},
        {"id": "C", "label": "其他（请说明）", "recommended": False},
    ]
    card = build_gate_interactive_card(
        thread_id="tid",
        summary="请确认",
        gate_id="confirm_change",
        web_url="http://127.0.0.1:8765/?thread_id=tid",
        choices=choices,
    )
    blob = str(card)
    assert "请择一" in blob
    assert "选择 A（推荐）：只删 placeholder" in blob
    assert "gate_decision" in blob and "approved" in blob
    assert "A（推荐）" in blob


def test_gate_card_multi_choice_groups_lists_options_without_buttons():
    groups = [
        {
            "id": "q1",
            "prompt": "范围？",
            "choices": [
                {"id": "A", "label": "方案一", "recommended": True},
                {"id": "B", "label": "方案二", "recommended": False},
            ],
        },
        {
            "id": "q2",
            "prompt": "测试？",
            "choices": [
                {"id": "A", "label": "全量", "recommended": False},
                {"id": "B", "label": "子集", "recommended": True},
            ],
        },
    ]
    card = build_gate_interactive_card(
        thread_id="tid",
        summary="请确认",
        gate_id="confirm_change",
        web_url="http://127.0.0.1:8765/?thread_id=tid",
        choice_groups=groups,
    )
    blob = str(card)
    assert "多道选择题" in blob
    assert "范围？" in blob
    assert "测试？" in blob
    assert "请择一" not in blob


def test_gate_card_single_choice_group_keeps_buttons():
    card = build_gate_interactive_card(
        thread_id="tid",
        summary="请确认",
        gate_id="confirm_change",
        web_url="http://127.0.0.1:8765/?thread_id=tid",
        choice_groups=[
            {
                "id": "q1",
                "prompt": "范围？",
                "choices": [
                    {"id": "A", "label": "一", "recommended": True},
                    {"id": "B", "label": "二", "recommended": False},
                ],
            }
        ],
    )
    assert "请择一" in str(card)


def test_clarification_card_choice_submits_reply():
    card = build_pm_clarification_interactive_card(
        thread_id="tid",
        summary="请确认",
        questions=["范围？"],
        web_url="http://127.0.0.1:8765/?thread_id=tid",
        choices=[
            {"id": "A", "label": "方案一", "recommended": True},
            {"id": "B", "label": "方案二", "recommended": False},
        ],
    )
    blob = str(card)
    assert "点选即提交答复" in blob
    assert "选择 A（推荐）：方案一" in blob
    event = {
        "action": {
            "value": {
                "thread_id": "tid",
                "hitl_action": "pm_clarification",
                "human_reply": "选择 A（推荐）：方案一",
            }
        }
    }
    parsed = parse_card_action_trigger(event)
    assert parsed["human_reply"].startswith("选择 A")


def test_feishu_main_webhook_card_trigger():
    client = TestClient(app)
    r = client.post(
        "/api/runs",
        json={"human_request": "webhook", "scenario_key": "npu_operator"},
    )
    tid = r.json()["thread_id"]
    body = {
        "header": {"event_type": "card.action.trigger"},
        "event": {
            "type": "card.action.trigger",
            "action_value": json.dumps(
                {
                    "thread_id": tid,
                    "hitl_action": "gate",
                    "gate_decision": "approved",
                }
            ),
        },
    }
    r2 = client.post("/api/webhooks/feishu", json=body)
    assert r2.status_code == 200
    data = r2.json()
    assert data.get("ok") is True
    assert data.get("toast")
    r3 = client.get(f"/api/runs/{tid}")
    assert r3.json()["awaiting_human"]["gate_id"] == "gate_architecture_review"


def test_feishu_clarification_form_webhook():
    client = TestClient(app)
    started = client.post(
        "/api/runs",
        json={"human_request": "clarify card", "scenario_key": "npu_operator"},
    )
    tid = started.json()["thread_id"]
    opened = client.post(
        f"/api/runs/{tid}/hitl/open",
        json={"kind": "pm_clarification", "questions": ["预算？"], "summary": "请确认"},
    )
    assert opened.status_code == 200
    body = {
        "header": {"event_type": "card.action.trigger"},
        "event": {
            "action": {
                "value": {"thread_id": tid, "hitl_action": "pm_clarification"},
                "form_value": {"reply": "上限 2 人周"},
            }
        },
    }
    submitted = client.post("/api/webhooks/feishu", json=body)
    assert submitted.status_code == 200
    assert submitted.json()["ok"] is True
    status = client.get(f"/api/runs/{tid}").json()
    assert status["awaiting_human"] is None or status["awaiting_human"]["kind"] != "pm_clarification"


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
