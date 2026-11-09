"""飞书状态查询与关卡批复的入站交互。"""

import json

from fastapi.testclient import TestClient

from geni_studio.hitl.feishu_session import register_awaiting_thread
from geni_studio.web.app import app


def _im(text: str, chat_id: str) -> dict:
    return {
        "header": {"event_type": "im.message.receive_v1"},
        "event": {
            "message": {
                "message_type": "text",
                "content": json.dumps({"text": text}, ensure_ascii=False),
                "chat_id": chat_id,
            },
            "sender": {"sender_id": {"open_id": "ou_status"}},
        },
    }


def _capture_send(monkeypatch):
    sent: list[dict] = []

    def fake(*, chat_id: str, open_id: str, card_json: str) -> bool:
        sent.append(
            {
                "chat_id": chat_id,
                "open_id": open_id,
                "card": json.loads(card_json),
            }
        )
        return True

    monkeypatch.setattr("geni_studio.hitl.feishu_status.deliver_status_card", fake)
    return sent


def test_status_query_does_not_approve_then_follow_up(monkeypatch):
    sent = _capture_send(monkeypatch)
    client = TestClient(app)
    started = client.post(
        "/api/runs",
        json={"human_request": "feishu status", "scenario_key": "npu_operator"},
    )
    assert started.status_code == 200
    tid = started.json()["thread_id"]
    chat = "oc_status_" + tid[:8]
    register_awaiting_thread(thread_id=tid, chat_id=chat)

    asked = client.post("/api/webhooks/feishu", json=_im("  状态  ", chat))
    assert asked.status_code == 200
    body = asked.json()
    assert body["status_query"] is True
    assert body["thread_id"] == tid
    assert body["sent"] is True
    assert body["lines"][0] == "阶段：等待人工"
    assert body["lines"][1] == "当前：需求确认"
    assert body["lines"][2] == "待办：待批复 · 需求确认"
    assert "thread_id=" in body["lines"][3]
    still = client.get(f"/api/runs/{tid}").json()
    assert still["phase"] == "awaiting_human"
    assert still["awaiting_human"]["gate_id"] == "gate_requirement_confirm"

    approved = client.post("/api/webhooks/feishu", json=_im("批准", chat))
    assert approved.status_code == 200
    assert approved.json()["phase"] == "awaiting_human"
    assert approved.json()["thread_id"] == tid

    where = client.post("/api/webhooks/feishu", json=_im("到哪了", chat))
    assert where.status_code == 200
    lines = where.json()["lines"]
    assert lines[0] == "阶段：等待人工"
    assert lines[1] == "当前：架构评审"
    assert lines[2] == "待办：待批复 · 架构评审"
    card_text = json.dumps(sent[-1]["card"], ensure_ascii=False)
    assert "阶段：等待人工" in card_text
    assert "架构评审" in card_text
    assert sent[-1]["chat_id"] == chat


def test_status_query_when_nothing_is_bound(monkeypatch):
    _capture_send(monkeypatch)
    client = TestClient(app)
    asked = client.post("/api/webhooks/feishu", json=_im("进度", "oc_empty_status"))
    assert asked.status_code == 200
    lines = asked.json()["lines"]
    assert lines == [
        "阶段：未启动",
        "当前：还没有进行中的轮次",
        "待办：无",
    ]
    assert asked.json()["thread_id"] == ""


def test_status_query_prefers_open_round_over_newer_finished(monkeypatch):
    _capture_send(monkeypatch)
    client = TestClient(app)
    chat = "oc_two_rounds"
    older = client.post(
        "/api/runs",
        json={"human_request": "older", "scenario_key": "npu_operator"},
    ).json()["thread_id"]
    newer = client.post(
        "/api/runs",
        json={"human_request": "newer", "scenario_key": "npu_operator"},
    ).json()["thread_id"]
    client.post(
        "/api/webhooks/feishu/card-action",
        json={"thread_id": newer, "gate_decision": "rejected", "human_reply": "停"},
    )
    register_awaiting_thread(thread_id=older, chat_id=chat)
    register_awaiting_thread(thread_id=newer, chat_id=chat)

    asked = client.post("/api/webhooks/feishu", json=_im("status", chat))
    body = asked.json()
    assert body["thread_id"] == older
    assert body["lines"][0] == "阶段：等待人工"
    assert body["lines"][1] == "当前：需求确认"


def test_status_query_reports_stopped(monkeypatch):
    _capture_send(monkeypatch)
    client = TestClient(app)
    started = client.post(
        "/api/runs",
        json={"human_request": "stop me", "scenario_key": "npu_operator"},
    )
    tid = started.json()["thread_id"]
    stopped = client.post(f"/api/runs/{tid}/stop")
    assert stopped.json()["phase"] == "stopped"
    chat = "oc_stopped_" + tid[:8]
    register_awaiting_thread(thread_id=tid, chat_id=chat)
    asked = client.post("/api/webhooks/feishu", json=_im("到哪", chat))
    lines = asked.json()["lines"]
    assert lines[0] == "阶段：已停止"
    assert lines[1] == "当前：需求确认"
    assert lines[2] == "待办：无"


def test_status_lines_for_paused_round(monkeypatch):
    from geni_studio.backends.runner import invoke_role
    from geni_studio.hitl.control import current_thread_id, request_pause
    from geni_studio.hitl.feishu_status import status_lines_for_thread
    from geni_studio.hitl.service import GraphRunService
    from geni_studio.workflows.default import graph

    def wrapped(**kwargs):
        request_pause(current_thread_id())
        return invoke_role(**kwargs)

    monkeypatch.setattr("geni_studio.backends.runner.invoke_role", wrapped)
    svc = GraphRunService(graph)
    st = svc.start(human_request="paused card", scenario_key="npu_operator")
    assert st.phase == "paused"
    lines = status_lines_for_thread(svc, st.thread_id, "http://127.0.0.1:8767/")
    assert lines[0] == "阶段：已暂停"
    assert lines[1] == "当前：项目经理起草"
    assert lines[2] == "待办：无"
    assert "继续" not in "\n".join(lines)
    assert "停止" not in "\n".join(lines)


def test_plain_status_sentence_is_not_a_query(monkeypatch):
    _capture_send(monkeypatch)
    client = TestClient(app)
    started = client.post(
        "/api/runs",
        json={"human_request": "not a query", "scenario_key": "npu_operator"},
    )
    tid = started.json()["thread_id"]
    chat = "oc_not_query_" + tid[:8]
    register_awaiting_thread(thread_id=tid, chat_id=chat)
    asked = client.post("/api/webhooks/feishu", json=_im("状态一下", chat))
    assert asked.json().get("ignored") == "gate_needs_decision_keyword"
    still = client.get(f"/api/runs/{tid}").json()
    assert still["awaiting_human"]["gate_id"] == "gate_requirement_confirm"
