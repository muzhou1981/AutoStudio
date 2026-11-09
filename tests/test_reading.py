"""人工待办阅读材料。"""

from geni_studio.hitl.reading import human_reading


def test_requirement_gate_reading_includes_the_spec():
    sections = human_reading(
        {"kind": "gate", "gate_id": "gate_requirement_confirm", "summary": "请批准"},
        {"requirement_spec": "验收标准\nAC-1", "testability_review": "可以单测"},
    )
    assert sections[0]["title"] == "需求说明"
    assert "AC-1" in sections[0]["body"]
    assert sections[1]["title"] == "可测性"


def test_clarification_lists_questions():
    sections = human_reading(
        {"kind": "pm_clarification", "questions": ["预算上限？", "范围？"]},
        {"requirement_spec": "只做 Mul"},
    )
    assert sections[0]["title"] == "待澄清"
    assert "1. 预算上限？" in sections[0]["body"]
    assert sections[1]["body"] == "只做 Mul"


def test_no_awaiting_means_no_reading():
    assert human_reading(None, {"requirement_spec": "x"}) == []
