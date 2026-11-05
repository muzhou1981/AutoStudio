from auto_studio.hitl.pm_clarification import (
    extract_pm_questions,
    merge_clarification_reply,
)
from auto_studio.hitl.service import GraphRunService
from auto_studio.workflows.default import graph


def test_extract_pm_questions_from_section():
    spec = "## 需求\n\n正文\n\n## 待澄清\n- 范围？\n- 优先级？\n"
    assert extract_pm_questions(spec) == ["范围？", "优先级？"]


def test_merge_clarification_reply():
    out = merge_clarification_reply("base", "仅 Mul", questions=["范围？"])
    assert "人类澄清答复" in out
    assert "仅 Mul" in out


def test_auto_pm_clarification_pause_and_resume(monkeypatch):
    def _fake_invoke(*, role_name: str, user_prompt: str, stub_note: str) -> str:
        if role_name == "project_manager":
            return "## 需求草案\n\n## 待澄清\n- 交付范围？\n"
        return f"[stub:{role_name}] {stub_note}"

    monkeypatch.setattr("auto_studio.backends.runner.invoke_role", _fake_invoke)
    svc = GraphRunService(graph)
    st = svc.start(human_request="demo", scenario_key="npu_operator")
    assert st.phase == "awaiting_human"
    assert st.awaiting_human is not None
    assert st.awaiting_human.kind == "pm_clarification"
    svc.submit_hitl(st.thread_id, human_reply="仅 Mul 算子", channel="web")
    st2 = svc.status(st.thread_id)
    assert "人类澄清答复" in (st2.values.get("requirement_spec") or "")
    assert st2.awaiting_human is None or st2.awaiting_human.kind == "gate"
