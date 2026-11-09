"""人工待办里给人读的正文。按关卡或待办类型挑选产物，不回传整份图状态。"""

from __future__ import annotations

from typing import Any

_GATE_SECTIONS: dict[str, tuple[tuple[str, str], ...]] = {
    "gate_requirement_confirm": (
        ("需求说明", "requirement_spec"),
        ("可测性", "testability_review"),
    ),
    "gate_architecture_review": (
        ("架构设计", "architecture_design"),
        ("任务计划", "task_plan"),
        ("预算", "budget_plan"),
    ),
    "gate_final_delivery": (
        ("交付报告", "delivery_report"),
        ("测试报告", "test_report"),
        ("质量结论", "qa_report"),
    ),
}

_MAX_BODY = 8000


def human_reading(
    awaiting: dict[str, Any] | None,
    values: dict[str, Any] | None,
) -> list[dict[str, str]]:
    if not awaiting:
        return []
    vals = values or {}
    kind = str(awaiting.get("kind") or "")
    sections: list[dict[str, str]] = []
    if kind == "pm_clarification":
        questions = awaiting.get("questions") or []
        if isinstance(questions, list) and questions:
            body = "\n".join(f"{index}. {question}" for index, question in enumerate(questions, 1))
            sections.append({"title": "待澄清", "body": body})
        _append(sections, "需求说明", vals.get("requirement_spec"))
    elif kind == "escalation":
        summary = str(awaiting.get("summary") or "").strip()
        if summary:
            sections.append({"title": "升级原因", "body": summary})
        _append(sections, "代码变更", vals.get("code_change"))
        _append(sections, "质量结论", vals.get("qa_report"))
        _append(sections, "成本", vals.get("cost_ledger"))
    elif kind == "gate":
        gate_id = str(awaiting.get("gate_id") or "")
        for title, key in _GATE_SECTIONS.get(gate_id, ()):
            _append(sections, title, vals.get(key))
        if not sections:
            summary = str(awaiting.get("summary") or "").strip()
            if summary:
                sections.append({"title": "说明", "body": summary})
    return sections


def _append(sections: list[dict[str, str]], title: str, raw: Any) -> None:
    text = str(raw or "").strip()
    if not text:
        return
    if len(text) > _MAX_BODY:
        text = text[:_MAX_BODY] + "…"
    sections.append({"title": title, "body": text})
