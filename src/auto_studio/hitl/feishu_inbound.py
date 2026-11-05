"""飞书入站：URL 校验、卡片回调解析。"""

from __future__ import annotations

import json
from typing import Any


class FeishuInboundError(ValueError):
    pass


def url_verification_response(body: dict[str, Any]) -> dict[str, str] | None:
    if body.get("type") == "url_verification" and body.get("challenge"):
        return {"challenge": str(body["challenge"])}
    if "challenge" in body and len(body) <= 2:
        return {"challenge": str(body["challenge"])}
    return None


def _parse_action_value(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise FeishuInboundError(f"action_value 非 JSON: {text[:120]}") from e
        return data if isinstance(data, dict) else {}
    return {}


def parse_card_action_trigger(event: dict[str, Any]) -> dict[str, str]:
    """从 card.action.trigger 事件或扁平 webhook 体解析 HITL 参数。"""
    action_value = event.get("action_value")
    if action_value is None and "event" in event:
        inner = event["event"]
        if isinstance(inner, dict):
            action_value = inner.get("action_value") or inner.get("action", {}).get(
                "value"
            )
    data = _parse_action_value(action_value)
    thread_id = str(data.get("thread_id") or "").strip()
    if not thread_id:
        raise FeishuInboundError("卡片回调缺少 thread_id")
    hitl_action = str(data.get("hitl_action") or "gate").strip().lower()
    if hitl_action == "escalation":
        choice = str(data.get("escalation_choice") or "").strip()
        if choice not in ("continue", "pause", "abort"):
            raise FeishuInboundError("升级卡片缺少 escalation_choice")
        return {
            "thread_id": thread_id,
            "hitl_action": "escalation",
            "escalation_choice": choice,
            "human_reply": str(data.get("human_reply") or "").strip(),
        }
    gate_decision = str(data.get("gate_decision") or "").strip()
    if gate_decision not in ("approved", "rejected"):
        raise FeishuInboundError("卡片回调缺少 gate_decision")
    return {
        "thread_id": thread_id,
        "hitl_action": "gate",
        "gate_decision": gate_decision,
        "human_reply": str(data.get("human_reply") or "").strip(),
    }


def card_action_toast_response(content: str = "已提交") -> dict[str, Any]:
    """飞书 card.action.trigger 同步响应（Toast）。"""
    return {"toast": {"type": "info", "content": content}}


def extract_event_payload(body: dict[str, Any]) -> dict[str, Any]:
    """兼容 lark-cli event consume NDJSON 与开放平台 event_callback。"""
    if "header" in body and "event" in body:
        header = body.get("header") or {}
        event_type = header.get("event_type") or body.get("type")
        event = body.get("event") or {}
        if isinstance(event, dict):
            event.setdefault("type", event_type)
        return event if isinstance(event, dict) else {}
    if body.get("type") == "card.action.trigger":
        return body
    return body
