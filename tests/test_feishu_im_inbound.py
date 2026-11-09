from fastapi.testclient import TestClient

from geni_studio.hitl.feishu_inbound import (
    normalize_im_hitl_reply,
    parse_im_message_receive,
    parse_thread_id_from_text,
)
from geni_studio.hitl.feishu_session import register_awaiting_thread, resolve_thread_id
from geni_studio.hitl.service import GraphRunService
from geni_studio.web.app import app
from geni_studio.workflows.default import graph


def test_parse_im_message_receive_text():
    body = {
        "header": {"event_type": "im.message.receive_v1"},
        "event": {
            "message": {
                "message_type": "text",
                "content": '{"text":"仅 Mul 算子"}',
                "chat_id": "oc_test",
            },
            "sender": {"sender_id": {"open_id": "ou_test"}},
        },
    }
    im = parse_im_message_receive(body)
    assert im is not None
    assert im["text"] == "仅 Mul 算子"
    assert im["chat_id"] == "oc_test"


def test_parse_thread_id_from_text():
    tid = "0393e93d-189b-4c2f-ab53-bfab539d0c66"
    assert parse_thread_id_from_text(f"RUN:{tid} 答复") == tid
    assert normalize_im_hitl_reply(f"RUN:{tid} 仅 Mul") == "仅 Mul"


def test_im_pm_clarification_submit_via_webhook():
    svc = GraphRunService(graph)
    st = svc.start(human_request="demo", scenario_key="npu_operator")
    tid = st.thread_id
    svc.open_hitl(
        tid,
        kind="pm_clarification",
        questions=["范围？"],
        summary="请确认",
    )
    register_awaiting_thread(thread_id=tid, chat_id="oc_test")
    assert resolve_thread_id(chat_id="oc_test") == tid

    client = TestClient(app)
    body = {
        "header": {"event_type": "im.message.receive_v1"},
        "event": {
            "message": {
                "message_type": "text",
                "content": '{"text":"仅 Mul"}',
                "chat_id": "oc_test",
            },
            "sender": {"sender_id": {"open_id": "ou_x"}},
        },
    }
    r = client.post("/api/webhooks/feishu", json=body)
    assert r.status_code == 200
    assert r.json()["thread_id"] == tid
    st2 = svc.status(tid)
    assert "人类澄清答复" in (st2.values.get("requirement_spec") or "") or st2.phase != "awaiting_human"
