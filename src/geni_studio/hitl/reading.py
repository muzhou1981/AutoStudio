"""人工待办里给人读的内容。按关卡或待办类型挑选产物，不回传整份图状态。

`human_reading` 给出产物正文，供解析选择题与飞书摘录；`human_review` 给页面列出
待审阅的产物、产出节点与结论，正文由检视区按节点展示。
"""

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

_GENERIC_GATE: tuple[tuple[str, str], ...] = (
    ("需求说明", "requirement_spec"),
    ("代码变更", "code_change"),
    ("测试报告", "test_report"),
    ("交付报告", "delivery_report"),
)

_ESCALATION: tuple[tuple[str, str], ...] = (
    ("代码变更", "code_change"),
    ("质量结论", "qa_report"),
    ("成本", "cost_ledger"),
)

_CLARIFICATION: tuple[tuple[str, str], ...] = (("需求说明", "requirement_spec"),)

_ARTIFACT_TITLES: dict[str, str] = {
    key: title
    for pairs in (*_GATE_SECTIONS.values(), _GENERIC_GATE, _ESCALATION)
    for title, key in pairs
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
    elif kind == "escalation":
        summary = str(awaiting.get("summary") or "").strip()
        if summary:
            sections.append({"title": "升级原因", "body": summary})
    for item in _review_sources(awaiting, vals):
        _append(sections, item["title"], artifact_text(vals, item["key"]))
    if kind == "gate" and not sections:
        summary = str(awaiting.get("summary") or "").strip()
        if summary:
            sections.append({"title": "说明", "body": summary})
    return sections


def human_review(
    awaiting: dict[str, Any] | None,
    values: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """待审阅的产物：标题、键、产出节点、字数与结构化结论；不含正文。"""
    if not awaiting:
        return []
    from geni_studio.verification.verdict import parse_verdict

    vals = values or {}
    out: list[dict[str, Any]] = []
    for item in _review_sources(awaiting, vals):
        text = artifact_text(vals, item["key"])
        if not text:
            continue
        verdict = parse_verdict(text)
        out.append({
            **item,
            "chars": len(text),
            "verdict": (
                {"status": verdict.status, "summary": verdict.summary, "ac": dict(verdict.ac)}
                if verdict is not None and verdict.source == "block"
                else None
            ),
        })
    return out


def artifact_text(values: dict[str, Any], key: str) -> str:
    raw = values.get(key)
    if raw is None:
        extra = values.get("extra_artifacts")
        raw = extra.get(key) if isinstance(extra, dict) else None
    return str(raw or "").strip()


def _review_sources(awaiting: dict[str, Any], values: dict[str, Any]) -> list[dict[str, str]]:
    kind = str(awaiting.get("kind") or "")
    if kind == "pm_clarification":
        pairs: tuple[tuple[str, str], ...] = _CLARIFICATION
    elif kind == "escalation":
        pairs = _ESCALATION
    elif kind == "gate":
        gate_id = str(awaiting.get("gate_id") or "")
        if gate_id in _GATE_SECTIONS:
            pairs = _GATE_SECTIONS[gate_id]
        else:
            upstream = _upstream_artifacts(values, gate_id)
            if upstream:
                return upstream
            pairs = _GENERIC_GATE
    else:
        return []
    return [{"title": title, "key": key, **_producer(values, key)} for title, key in pairs]


def _workflow_nodes(values: dict[str, Any]) -> list[dict[str, Any]]:
    raw = values.get("workflow_nodes")
    return [item for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _upstream_artifacts(values: dict[str, Any], gate_id: str) -> list[dict[str, str]]:
    """流程里位于上一个决策点与本决策点之间的活动产物，即本决策点要审阅的内容。"""
    nodes = _workflow_nodes(values)
    index = next((i for i, item in enumerate(nodes) if str(item.get("id") or "") == gate_id), -1)
    if index < 0:
        return []
    found: list[dict[str, str]] = []
    for node in reversed(nodes[:index]):
        kind = node.get("kind")
        if kind == "gate":
            break
        if kind != "activity":
            continue
        node_id = str(node.get("id") or "")
        label = str(node.get("label") or node_id)
        for key in reversed([str(k) for k in node.get("artifacts") or [] if isinstance(k, str) and k]):
            found.append({"title": _ARTIFACT_TITLES.get(key) or label, "key": key, "node": node_id, "node_label": label})
    unique: dict[str, dict[str, str]] = {}
    for item in reversed(found):
        unique.setdefault(item["key"], item)
    return list(unique.values())


def _producer(values: dict[str, Any], key: str) -> dict[str, str]:
    """产出该产物的最后一个活动节点；流程没有记录时按内置流程的节点表查找。"""
    for node in reversed(_workflow_nodes(values)):
        if node.get("kind") == "activity" and key in (node.get("artifacts") or []):
            node_id = str(node.get("id") or "")
            return {"node": node_id, "node_label": str(node.get("label") or node_id)}
    from geni_studio.hitl.rail import NODE_ARTIFACTS, label_for

    for node_id, keys in NODE_ARTIFACTS.items():
        if key in keys and not node_id.startswith("gate_"):
            return {"node": node_id, "node_label": label_for(node_id)}
    return {"node": "", "node_label": ""}


def _append(sections: list[dict[str, str]], title: str, raw: Any) -> None:
    text = str(raw or "").strip()
    if not text:
        return
    if len(text) > _MAX_BODY:
        text = text[:_MAX_BODY] + "…"
    sections.append({"title": title, "body": text})
