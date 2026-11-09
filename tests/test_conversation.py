"""角色会话落盘后可以按角色读回。"""

from geni_studio.hitl.conversation import (
    append_step,
    begin_turn,
    conversation_view,
    finish_turn,
    read_artifact_text,
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
