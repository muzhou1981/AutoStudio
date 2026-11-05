"""飞书 Gate 交互卡片（Card 2.0）构造。"""

from __future__ import annotations

import json
from typing import Any


def gate_card_action_value(*, thread_id: str, gate_decision: str) -> dict[str, str]:
    return {"thread_id": thread_id, "gate_decision": gate_decision}


def build_gate_interactive_card(
    *,
    thread_id: str,
    summary: str,
    gate_id: str | None,
    web_url: str,
) -> dict[str, Any]:
    title = "软件工厂 · 项目经理"
    subtitle = gate_id or "人工关卡"
    body_md = summary or "请在下方批准或驳回；复杂说明请打开 Web。"
    return {
        "schema": "2.0",
        "config": {"update_multi": True, "width_mode": "default"},
        "header": {
            "title": {"tag": "plain_text", "content": title},
            "subtitle": {"tag": "plain_text", "content": subtitle},
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
                    "tag": "markdown",
                    "content": f"Run：`{thread_id}`",
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


def card_content_json(card: dict[str, Any]) -> str:
    """供 lark-cli `--msg-type interactive --content` 使用。"""
    return json.dumps(card, ensure_ascii=False)
