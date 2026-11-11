"""飞书 Gate 交互卡片（Card 2.0）构造。"""

from __future__ import annotations

import json
from typing import Any

from geni_studio.hitl.choices import choice_reply_line

_CHOICE_BTN_LABEL_MAX = 22


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
    node_label: str = "",
    reject_label: str = "",
    excerpt: str = "",
    choices: list[dict[str, Any]] | None = None,
    choice_groups: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    title = "软件工厂 · 项目经理"
    shown = node_label.strip() or _node_label(gate_id)
    body_md = _awaiting_lines(kind="gate", node_label=shown)
    if reject_label.strip():
        body_md += f"\n不通过将前往「{reject_label.strip()}」，然后继续。"
    else:
        body_md += "\n不通过将结束本轮。"
    if summary:
        body_md += f"\n\n{summary}"
    if excerpt.strip():
        body_md += f"\n\n{excerpt.strip()}"
    body_md += f"\n\nRun：`{thread_id}`"
    elements: list[dict[str, Any]] = [
        {
            "tag": "markdown",
            "content": body_md,
            "text_align": "left",
        },
    ]
    elements.extend(
        _hitl_choice_elements(
            thread_id=thread_id,
            choices=choices or [],
            choice_groups=choice_groups or [],
            hitl_action="gate",
            gate_decision="approved",
        )
    )
    elements.extend(
        [
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
                                    "text": {"tag": "plain_text", "content": "不通过"},
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
        ]
    )
    return {
        "schema": "2.0",
        "config": {"update_multi": True, "width_mode": "default"},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "subtitle": {"tag": "plain_text", "content": shown},
            "template": "blue",
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 20px 12px",
            "elements": elements,
        },
    }


def build_pm_clarification_interactive_card(
    *,
    thread_id: str,
    summary: str,
    questions: list[str],
    web_url: str,
    choices: list[dict[str, Any]] | None = None,
    choice_groups: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    title = "软件工厂 · 需求澄清"
    node_label = "项目经理起草"
    q_md = "\n".join(f"- {q}" for q in questions) if questions else "（见 Web）"
    body_md = _awaiting_lines(kind="pm_clarification", node_label=node_label)
    body_md += "\n\n" + (summary or "请答复以下问题，工厂方可继续。")
    body_md += "\n\n" + q_md
    body_md += f"\n\nRun：`{thread_id}`"
    elements: list[dict[str, Any]] = [
        {"tag": "markdown", "content": body_md, "text_align": "left"},
    ]
    elements.extend(
        _hitl_choice_elements(
            thread_id=thread_id,
            choices=choices or [],
            choice_groups=choice_groups or [],
            hitl_action="pm_clarification",
            gate_decision=None,
        )
    )
    elements.extend(
        [
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
        ]
    )
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
            "elements": elements,
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


def build_settled_gate_card(*, node_label: str, decision_line: str) -> dict[str, Any]:
    """批复之后替换原卡片，去掉还能再点的按钮。"""
    return {
        "schema": "2.0",
        "config": {"update_multi": True, "width_mode": "default"},
        "header": {
            "title": {"tag": "plain_text", "content": "软件工厂 · 项目经理"},
            "subtitle": {"tag": "plain_text", "content": node_label or "决策点"},
            "template": "green",
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 20px 12px",
            "elements": [
                {"tag": "markdown", "content": decision_line, "text_align": "left"},
            ],
        },
    }


def card_content_json(card: dict[str, Any]) -> str:
    """供 lark-cli `--msg-type interactive --content` 使用。"""
    return json.dumps(card, ensure_ascii=False)


def _node_label(node_id: str | None) -> str:
    from geni_studio.hitl.rail import label_for

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


def _choice_button_label(choice: dict[str, Any]) -> str:
    letter = str(choice.get("id") or "").strip()
    label = str(choice.get("label") or "").strip()
    prefix = f"{letter}（推荐）" if choice.get("recommended") else letter
    if not label:
        return prefix
    short = label if len(label) <= _CHOICE_BTN_LABEL_MAX else label[: _CHOICE_BTN_LABEL_MAX - 1] + "…"
    return f"{prefix}：{short}"


def _choice_column_set(
    *,
    thread_id: str,
    choices: list[dict[str, Any]],
    hitl_action: str,
    gate_decision: str | None,
) -> dict[str, Any]:
    columns: list[dict[str, Any]] = []

    def _btn(choice: dict[str, Any]) -> dict[str, Any]:
        value: dict[str, str] = {
            "thread_id": thread_id,
            "hitl_action": hitl_action,
            "human_reply": choice_reply_line(choice),
        }
        if gate_decision:
            value["gate_decision"] = gate_decision
        btn_type = "primary_filled" if choice.get("recommended") else "default"
        return {
            "tag": "button",
            "text": {"tag": "plain_text", "content": _choice_button_label(choice)},
            "type": btn_type,
            "width": "fill",
            "behaviors": [{"type": "callback", "value": value}],
        }

    for choice in choices:
        columns.append(
            {
                "tag": "column",
                "width": "weighted",
                "weight": 1,
                "elements": [_btn(choice)],
            }
        )
    return {"tag": "column_set", "flex_mode": "stretch", "columns": columns}


def _multi_choice_groups_markdown(choice_groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(choice_groups) <= 1:
        return []
    lines = ["**多道选择题**：飞书内请打开 Web 逐题点选；或在下批复附言中写明各题选择。"]
    for index, group in enumerate(choice_groups, start=1):
        prompt = str(group.get("prompt") or "").strip() or f"问题 {index}"
        lines.append(f"\n**{prompt}**")
        for choice in group.get("choices") or []:
            lines.append(f"- {choice_reply_line(choice)}")
    return [{"tag": "markdown", "content": "\n".join(lines), "text_align": "left"}]


def _hitl_choice_elements(
    *,
    thread_id: str,
    choices: list[dict[str, Any]],
    choice_groups: list[dict[str, Any]],
    hitl_action: str,
    gate_decision: str | None,
) -> list[dict[str, Any]]:
    if len(choice_groups) > 1:
        return _multi_choice_groups_markdown(choice_groups)
    if len(choice_groups) == 1:
        choices = list(choice_groups[0].get("choices") or [])
    if hitl_action == "gate":
        return _gate_choice_elements(thread_id=thread_id, choices=choices)
    return _clarification_choice_elements(thread_id=thread_id, choices=choices)


def _gate_choice_elements(
    *, thread_id: str, choices: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if len(choices) < 2:
        return []
    chunks: list[dict[str, Any]] = [
        {
            "tag": "markdown",
            "content": "**请择一**（点选即批准并写入附言）",
            "text_align": "left",
        }
    ]
    for index in range(0, len(choices), 3):
        row = choices[index : index + 3]
        chunks.append(
            _choice_column_set(
                thread_id=thread_id,
                choices=row,
                hitl_action="gate",
                gate_decision="approved",
            )
        )
    return chunks


def _clarification_choice_elements(
    *, thread_id: str, choices: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    if len(choices) < 2:
        return []
    chunks: list[dict[str, Any]] = [
        {
            "tag": "markdown",
            "content": "**请择一**（点选即提交答复）",
            "text_align": "left",
        }
    ]
    for index in range(0, len(choices), 3):
        row = choices[index : index + 3]
        chunks.append(
            _choice_column_set(
                thread_id=thread_id,
                choices=row,
                hitl_action="pm_clarification",
                gate_decision=None,
            )
        )
    return chunks


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
