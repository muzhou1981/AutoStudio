"""飞书入站：URL 校验、卡片回调解析。"""

from __future__ import annotations

import json
import re
from typing import Any

_THREAD_IN_TEXT = re.compile(
    r"(?:^|\s)(?:RUN:|run:)([0-9a-fA-F-]{36})(?:\s|$)",
)


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


def _action_parts(event: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    action = event.get("action") if isinstance(event.get("action"), dict) else {}
    raw = event.get("action_value")
    if raw is None and "event" in event and isinstance(event["event"], dict):
        inner = event["event"]
        nested = inner.get("action") if isinstance(inner.get("action"), dict) else {}
        raw = inner.get("action_value")
        if raw is None:
            raw = nested.get("value")
        if not action:
            action = nested
    if raw is None:
        raw = action.get("value")
    form = action.get("form_value") or event.get("form_value") or {}
    if not isinstance(form, dict):
        form = {}
    return _parse_action_value(raw), form


def card_operator_open_id(event: dict[str, Any]) -> str:
    """卡片回调中点击者的 open_id。"""
    for source in (event, event.get("event") if isinstance(event.get("event"), dict) else {}):
        operator = source.get("operator") if isinstance(source.get("operator"), dict) else {}
        found = str(operator.get("open_id") or source.get("open_id") or "").strip()
        if found:
            return found
    return ""


def parse_card_action_trigger(event: dict[str, Any]) -> dict[str, str]:
    """从 card.action.trigger 事件或扁平 webhook 体解析 HITL 参数。"""
    data, form = _action_parts(event)
    thread_id = str(data.get("thread_id") or "").strip()
    if not thread_id:
        raise FeishuInboundError("卡片回调缺少 thread_id")
    hitl_action = str(data.get("hitl_action") or "gate").strip().lower()
    if hitl_action == "pm_clarification":
        reply = str(form.get("reply") or data.get("human_reply") or "").strip()
        if not reply:
            raise FeishuInboundError("澄清卡片缺少答复")
        return {
            "thread_id": thread_id,
            "hitl_action": "pm_clarification",
            "human_reply": reply,
        }
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
        "branch_choice": str(data.get("branch_choice") or "").strip(),
    }


def card_action_toast_response(content: str = "已提交") -> dict[str, Any]:
    """飞书 card.action.trigger 同步响应（Toast）。"""
    return {"toast": {"type": "info", "content": content}}


def event_type_from_body(body: dict[str, Any]) -> str:
    if "header" in body and isinstance(body["header"], dict):
        et = body["header"].get("event_type")
        if et:
            return str(et)
    return str(body.get("type") or body.get("event_type") or "")


def parse_thread_id_from_text(text: str) -> str | None:
    m = _THREAD_IN_TEXT.search(text.strip())
    return m.group(1) if m else None


def parse_im_message_receive(body: dict[str, Any]) -> dict[str, str] | None:
    """解析 im.message.receive_v1 文本消息。"""
    if event_type_from_body(body) != "im.message.receive_v1":
        return None
    event = body.get("event") if "event" in body else body
    if not isinstance(event, dict):
        return None
    message = event.get("message") or {}
    if str(message.get("message_type") or "") != "text":
        return None
    raw_content = message.get("content") or "{}"
    try:
        content = json.loads(raw_content) if isinstance(raw_content, str) else raw_content
    except json.JSONDecodeError:
        return None
    if not isinstance(content, dict):
        return None
    text = str(content.get("text") or "").strip()
    if not text:
        return None
    chat_id = str(message.get("chat_id") or event.get("chat_id") or "").strip()
    sender = event.get("sender") or {}
    sender_id = sender.get("sender_id") or {}
    open_id = str(sender_id.get("open_id") or "").strip()
    return {"text": text, "chat_id": chat_id, "open_id": open_id}


def normalize_im_hitl_reply(text: str) -> str:
    """去掉 RUN:uuid 前缀后的澄清正文。"""
    return _THREAD_IN_TEXT.sub(" ", text).strip()


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
