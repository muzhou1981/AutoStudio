"""飞书 Gate 交互卡片（Card 2.0）构造。"""

from __future__ import annotations

import json
from typing import Any


def gate_card_action_value(*, thread_id: str, gate_decision: str) -> dict[str, str]:
    return {
        "thread_id": thread_id,
        "hitl_action": "gate",
        "gate_decision": gate_decision,
    }


def escalation_card_action_value(
    *, thread_id: str, escalation_choice: str
) -> dict[str, str]:
    return {
        "thread_id": thread_id,
        "hitl_action": "escalation",
        "escalation_choice": escalation_choice,
    }


def build_gate_interactive_card(
    *,
    thread_id: str,
    summary: str,
    gate_id: str | None,
    web_url: str,
) -> dict[str, Any]:
    title = "软件工厂 · 项目经理"
    node_label = _node_label(gate_id)
    body_md = _awaiting_lines(kind="gate", node_label=node_label)
    if summary:
        body_md += f"\n\n{summary}"
    body_md += f"\n\nRun：`{thread_id}`"
    return {
        "schema": "2.0",
        "config": {"update_multi": True, "width_mode": "default"},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "subtitle": {"tag": "plain_text", "content": node_label},
            "template": "blue",
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 20px 12px",
            "elements": [
                {
                    "tag": "markdown",
                    "content": body_md,
                    "text_align": "left",
                },
                {
                    "tag": "column_set",
                    "flex_mode": "stretch",
                    "columns": [
                        {
                            "tag": "column",
                            "width": "weighted",
                            "weight": 1,
                            "elements": [
                                {
                                    "tag": "button",
                                    "text": {"tag": "plain_text", "content": "批准"},
                                    "type": "primary_filled",
                                    "width": "fill",
                                    "behaviors": [
                                        {
                                            "type": "callback",
                                            "value": gate_card_action_value(
                                                thread_id=thread_id,
                                                gate_decision="approved",
                                            ),
                                        }
                                    ],
                                }
                            ],
                        },
                        {
                            "tag": "column",
                            "width": "weighted",
                            "weight": 1,
                            "elements": [
                                {
                                    "tag": "button",
                                    "text": {"tag": "plain_text", "content": "驳回"},
                                    "type": "danger",
                                    "width": "fill",
                                    "behaviors": [
                                        {
                                            "type": "callback",
                                            "value": gate_card_action_value(
                                                thread_id=thread_id,
                                                gate_decision="rejected",
                                            ),
                                        }
                                    ],
                                }
                            ],
                        },
                    ],
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "在 Web 中打开"},
                    "type": "primary_text",
                    "width": "fill",
                    "behaviors": [
                        {"type": "open_url", "default_url": web_url},
                    ],
                },
            ],
        },
    }


def build_pm_clarification_interactive_card(
    *,
    thread_id: str,
    summary: str,
    questions: list[str],
    web_url: str,
) -> dict[str, Any]:
    title = "软件工厂 · 需求澄清"
    node_label = "项目经理起草"
    q_md = "\n".join(f"- {q}" for q in questions) if questions else "（见 Web）"
    body_md = _awaiting_lines(kind="pm_clarification", node_label=node_label)
    body_md += "\n\n" + (summary or "请答复以下问题，工厂方可继续。")
    body_md += "\n\n" + q_md
    body_md += f"\n\nRun：`{thread_id}`"
    return {
        "schema": "2.0",
        "config": {"update_multi": True, "width_mode": "default"},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": "wathet",
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 20px 12px",
            "elements": [
                {"tag": "markdown", "content": body_md, "text_align": "left"},
                {
                    "tag": "form",
                    "name": "clarification",
                    "elements": [
                        {
                            "tag": "input",
                            "name": "reply",
                            "placeholder": {"tag": "plain_text", "content": "逐条回答"},
                            "width": "fill",
                        },
                        {
                            "tag": "button",
                            "name": "submit_reply",
                            "text": {"tag": "plain_text", "content": "提交答复"},
                            "type": "primary_filled",
                            "width": "fill",
                            "form_action_type": "submit",
                            "behaviors": [
                                {
                                    "type": "callback",
                                    "value": {
                                        "thread_id": thread_id,
                                        "hitl_action": "pm_clarification",
                                    },
                                }
                            ],
                        },
                    ],
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "在 Web 中答复"},
                    "type": "primary_text",
                    "width": "fill",
                    "behaviors": [{"type": "open_url", "default_url": web_url}],
                },
            ],
        },
    }


def build_escalation_interactive_card(
    *,
    thread_id: str,
    summary: str,
    web_url: str,
) -> dict[str, Any]:
    title = "软件工厂 · 升级决策"
    node_label = "开发"
    body_md = _awaiting_lines(kind="escalation", node_label=node_label)
    body_md += "\n\n" + (summary or "开发回退或预算异常，请选择后续动作。")
    body_md += f"\n\nRun：`{thread_id}`"
    choices = (
        ("continue", "继续", "primary_filled"),
        ("pause", "暂停", "default"),
        ("abort", "终止", "danger"),
    )

    def _btn(choice: str, label: str, btn_type: str) -> dict[str, Any]:
        return {
            "tag": "button",
            "text": {"tag": "plain_text", "content": label},
            "type": btn_type,
            "width": "fill",
            "behaviors": [
                {
                    "type": "callback",
                    "value": escalation_card_action_value(
                        thread_id=thread_id,
                        escalation_choice=choice,
                    ),
                }
            ],
        }

    columns = [
        {
            "tag": "column",
            "width": "weighted",
            "weight": 1,
            "elements": [_btn(c, label, t)],
        }
        for c, label, t in choices
    ]
    return {
        "schema": "2.0",
        "config": {"update_multi": True, "width_mode": "default"},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "template": "orange",
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 20px 12px",
            "elements": [
                {"tag": "markdown", "content": body_md, "text_align": "left"},
                {"tag": "column_set", "flex_mode": "stretch", "columns": columns},
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "在 Web 中打开"},
                    "type": "primary_text",
                    "width": "fill",
                    "behaviors": [{"type": "open_url", "default_url": web_url}],
                },
            ],
        },
    }


def card_content_json(card: dict[str, Any]) -> str:
    """供 lark-cli `--msg-type interactive --content` 使用。"""
    return json.dumps(card, ensure_ascii=False)


def _node_label(node_id: str | None) -> str:
    from auto_studio.hitl.rail import label_for

    if not node_id:
        return "当前节点"
    return label_for(node_id)


def _open_button(web_url: str) -> dict[str, Any]:
    return {
        "tag": "button",
        "text": {"tag": "plain_text", "content": "在 Web 中打开"},
        "type": "primary_text",
        "width": "fill",
        "behaviors": [{"type": "open_url", "default_url": web_url}],
    }


def _awaiting_lines(*, kind: str, node_label: str) -> str:
    if kind == "pm_clarification":
        todo = f"待澄清 · {node_label}"
    elif kind == "escalation":
        todo = f"待决策 · {node_label}"
    else:
        todo = f"待批复 · {node_label}"
    return f"阶段：等待人工\n当前：{node_label}\n待办：{todo}"


def build_status_interactive_card(*, lines: list[str], web_url: str = "") -> dict[str, Any]:
    elements: list[dict[str, Any]] = [
        {"tag": "markdown", "content": "\n".join(lines), "text_align": "left"},
    ]
    if web_url:
        elements.append(_open_button(web_url))
    return {
        "schema": "2.0",
        "config": {"update_multi": True, "width_mode": "default"},
        "header": {
            "title": {"tag": "plain_text", "content": "软件工厂 · 当前状态"},
            "template": "blue",
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 20px 12px",
            "elements": elements,
        },
    }
