"""模型会话按节点落盘，旧的按角色目录仍可读回。"""

from geni_studio.hitl.conversation import (
    append_step,
    begin_turn,
    conversation_view,
    finish_turn,
    read_artifact_text,
    record_human_answer,
)


def test_turn_keeps_prompt_steps_and_result(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("geni_studio.hitl.conversation.factory_root", lambda: tmp_path)
    path = begin_turn(
        "tid",
        "developer",
        agent_id="agent-1",
        model="default",
        prompt="角色定义\n\n---\n\n## 本轮任务\n\n写代码",
    )
    append_step(path, {"type": "toolCall", "message": {"name": "shell"}})
    finish_turn(path, "写完了")
    view = conversation_view("tid", "developer")
    events = view["turns"][0]["events"]
    assert events[0]["agent_id"] == "agent-1"
    assert events[0]["prompt"].startswith("角色定义")
    assert events[1]["step"]["type"] == "toolCall"
    assert events[2]["text"] == "写完了"
    root = tmp_path / ".geni_studio" / "runs" / "tid"
    root.mkdir(parents=True, exist_ok=True)
    (root / "requirement_spec.md").write_text("# 需求说明\n\n正文\n", encoding="utf-8")
    assert read_artifact_text("tid", "requirement_spec").startswith("# 需求说明")
    assert read_artifact_text("tid", "../secret") == ""


def test_turns_are_archived_per_node(tmp_path, monkeypatch) -> None:
    from geni_studio.hitl.conversation import node_role

    monkeypatch.setattr("geni_studio.hitl.conversation.factory_root", lambda: tmp_path)
    first = begin_turn("tid2", "developer", agent_id="a", model="m", prompt="实现 A", node="impl_a")
    finish_turn(first, "A 完成")
    second = begin_turn("tid2", "developer", agent_id="b", model="m", prompt="实现 B", node="impl_b")
    finish_turn(second, "B 完成")
    view_a = conversation_view("tid2", "developer", node="impl_a")
    view_b = conversation_view("tid2", "developer", node="impl_b")
    assert [t["events"][0]["prompt"] for t in view_a["turns"]] == ["实现 A"]
    assert [t["events"][0]["prompt"] for t in view_b["turns"]] == ["实现 B"]
    assert view_a["turns"][0]["events"][0]["role"] == "developer"
    assert view_a["turns"][0]["events"][0]["node"] == "impl_a"

    values = {"workflow_nodes": [{"id": "impl_a", "role": "developer"}, {"id": "audit", "role": "compliance"}]}
    assert node_role(values, "audit") == "compliance"
    assert node_role({}, "developer") == "developer"


def test_legacy_role_folder_is_still_readable(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("geni_studio.hitl.conversation.factory_root", lambda: tmp_path)
    legacy = begin_turn("tid3", "qa", agent_id="q", model="m", prompt="旧会话", node="")
    finish_turn(legacy, "旧结论")
    assert conversation_view("tid3", "qa", node="qa")["turns"][0]["events"][0]["prompt"] == "旧会话"


def test_conversation_endpoint_resolves_custom_workflow_nodes(tmp_path, monkeypatch) -> None:
    from fastapi.testclient import TestClient

    from geni_studio.web.app import app, run_service

    monkeypatch.setattr("geni_studio.hitl.conversation.factory_root", lambda: tmp_path)
    st = run_service().start(human_request="会话节点", scenario_key="npu_operator")
    run_service()._bound(st.thread_id).update_state(
        run_service()._config(st.thread_id),
        {"workflow_nodes": [{"id": "custom_audit", "role": "compliance", "label": "审计", "kind": "activity"}]},
    )
    path = begin_turn(st.thread_id, "compliance", agent_id="c", model="m", prompt="审计提示", node="custom_audit")
    finish_turn(path, "审计结论")
    data = TestClient(app).get(f"/api/runs/{st.thread_id}/conversations/custom_audit").json()
    assert data["role"] == "compliance"
    assert data["node"] == "custom_audit"
    assert data["turns"][0]["events"][0]["prompt"] == "审计提示"


_ASK = "先确认：\n\n**范围怎么定？**\n\n- **A（推荐）**：只改 Run 页\n- **B**：全站一起改\n\n请选 A / B。"


def test_turn_questions_hide_the_lines_shown_by_the_card(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("geni_studio.hitl.conversation.factory_root", lambda: tmp_path)
    path = begin_turn("tq", "project_manager", agent_id="a", model="m", prompt="p", node="hear")
    finish_turn(path, _ASK)
    question = conversation_view("tq", node="hear")["turns"][0]["questions"][0]
    assert question["prompt"] == "范围怎么定？"
    assert question["hide"] == ["**范围怎么定？**", "- **A（推荐）**：只改 Run 页", "- **B**：全站一起改"]


def test_human_answer_goes_to_the_turn_that_asked_once(tmp_path, monkeypatch) -> None:
    from geni_studio.hitl.choices import extract_choice_groups

    monkeypatch.setattr("geni_studio.hitl.conversation.factory_root", lambda: tmp_path)
    asked = begin_turn("ta", "project_manager", agent_id="a", model="m", prompt="p", node="hear")
    finish_turn(asked, _ASK)
    other = begin_turn("ta", "developer", agent_id="b", model="m", prompt="p", node="change_code")
    finish_turn(other, "改完了")
    groups = extract_choice_groups(_ASK)
    assert record_human_answer("ta", groups, reply="同意A", decision="approved", channel="web") == asked
    assert record_human_answer("ta", groups, reply="选择 B", decision="approved", channel="web") is None
    events = conversation_view("ta", node="hear")["turns"][0]["events"]
    human = [e for e in events if e["kind"] == "human"]
    assert len(human) == 1
    assert human[0]["answers"] == {"q1": "A"}
    assert human[0]["decision"] == "approved"
    assert all(e["kind"] != "human" for e in conversation_view("ta", node="change_code")["turns"][0]["events"])


def test_gate_submit_writes_the_answer_into_the_conversation(tmp_path, monkeypatch) -> None:
    from geni_studio.hitl.service import GraphRunService
    from geni_studio.workflows.default import graph

    monkeypatch.setattr("geni_studio.hitl.conversation.factory_root", lambda: tmp_path)
    svc = GraphRunService(graph)
    st = svc.start(human_request="demo", scenario_key="npu_operator")
    assert st.awaiting_human is not None and st.awaiting_human.kind == "gate"
    svc._bound(st.thread_id).update_state(svc._config(st.thread_id), {"requirement_spec": _ASK})
    path = begin_turn(st.thread_id, "project_manager", agent_id="a", model="m", prompt="p", node="hear")
    finish_turn(path, _ASK)
    svc.submit_hitl(st.thread_id, gate_decision="approved", human_reply="选择 B：全站一起改")
    human = [e for e in conversation_view(st.thread_id, node="hear")["turns"][0]["events"] if e["kind"] == "human"]
    assert human and human[0]["answers"] == {"q1": "B"}
    assert human[0]["reply"] == "选择 B：全站一起改"
