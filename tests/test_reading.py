"""人工待办阅读材料。"""

from geni_studio.hitl.choices import choices_from_reading
from geni_studio.hitl.reading import human_reading, human_review


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


def test_custom_gate_includes_requirement_spec():
    sections = human_reading(
        {"kind": "gate", "gate_id": "confirm_change", "summary": "请批准变更"},
        {"requirement_spec": "A：方案一\nB：方案二\n"},
    )
    assert sections[0]["title"] == "需求说明"
    assert "方案一" in sections[0]["body"]
    choices = choices_from_reading(sections)
    assert [c["id"] for c in choices] == ["A", "B"]


_SELF_DEV_NODES = [
    {"id": "start", "label": "启动", "kind": "start", "artifacts": []},
    {"id": "hear", "label": "听清改动", "kind": "activity", "artifacts": ["requirement_spec"]},
    {"id": "confirm_change", "label": "确认改动", "kind": "gate", "reject_to": "hear"},
    {"id": "change_code", "label": "改代码", "kind": "activity", "artifacts": ["code_change"]},
    {"id": "self_check", "label": "自行核对", "kind": "activity", "artifacts": ["ui_check"]},
    {"id": "review", "label": "看结果", "kind": "gate", "reject_to": "change_code"},
    {"id": "handoff", "label": "写交付说明", "kind": "activity", "artifacts": ["delivery_report"]},
]


def _self_dev_values():
    verdict = '```verdict\n{"status": "pass", "ac": {"AC-1": "pass", "AC-2": "untested"}, "summary": "界面验收通过"}\n```'
    return {
        "workflow_nodes": _SELF_DEV_NODES,
        "requirement_spec": "需求" * 3000,
        "code_change": "改动说明",
        "delivery_report": "不该出现",
        "extra_artifacts": {"ui_check": "核对正文\n\n" + verdict},
    }


def test_workflow_gate_reviews_only_the_activities_since_the_previous_gate():
    awaiting = {"kind": "gate", "gate_id": "review", "summary": "看结果：请批准"}
    sections = human_reading(awaiting, _self_dev_values())
    assert [s["title"] for s in sections] == ["代码变更", "自行核对"]

    review = human_review(awaiting, _self_dev_values())
    assert [(r["key"], r["node"], r["node_label"]) for r in review] == [
        ("code_change", "change_code", "改代码"),
        ("ui_check", "self_check", "自行核对"),
    ]
    assert review[0]["verdict"] is None
    assert review[1]["verdict"] == {"status": "pass", "summary": "界面验收通过", "ac": {"AC-1": "pass", "AC-2": "untested"}}
    assert "body" not in review[0]


def test_review_skips_empty_artifacts_and_points_clarification_at_the_spec():
    values = {**_self_dev_values(), "code_change": ""}
    review = human_review({"kind": "gate", "gate_id": "review"}, values)
    assert [r["key"] for r in review] == ["ui_check"]
    clarify = human_review({"kind": "pm_clarification", "questions": ["范围？"]}, values)
    assert clarify[0]["key"] == "requirement_spec"
    assert clarify[0]["node"] == "hear"
    assert clarify[0]["chars"] == 6000
    assert human_review(None, values) == []


def test_status_payload_reports_review_and_reject_target(monkeypatch):
    from types import SimpleNamespace

    from geni_studio.hitl import presenter

    ah = SimpleNamespace(kind="gate", since="", gate_id="review", questions=[], summary="看结果：请批准")
    st = SimpleNamespace(thread_id="t", phase="awaiting_human", next_nodes=("review",), awaiting_human=ah)
    values = _self_dev_values()
    assert presenter.gate_reject_label(values, "review") == "改代码"
    assert presenter.gate_reject_label(values, "gate_final_delivery") == ""
    monkeypatch.setattr(presenter, "rail_for", lambda _st: {"cells": []})
    body = presenter.status_payload(st, values)
    assert body["awaiting_human"]["reject_label"] == "改代码"
    assert [r["key"] for r in body["review"]] == ["code_change", "ui_check"]
