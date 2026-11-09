"""飞书入站 Webhook / 卡片回调。"""

from __future__ import annotations

import os
import secrets
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from geni_studio.hitl.feishu_cards import build_settled_gate_card
from geni_studio.hitl.feishu_inbound import (
    FeishuInboundError,
    card_action_toast_response,
    event_type_from_body,
    extract_event_payload,
    normalize_im_hitl_reply,
    parse_card_action_trigger,
    parse_im_message_receive,
    parse_thread_id_from_text,
    url_verification_response,
)
from geni_studio.hitl.feishu_notify import (
    gate_presentation,
    notify_awaiting_human_via_lark_cli,
)
from geni_studio.hitl.feishu_session import bound_thread_ids
from geni_studio.hitl.feishu_status import answer_status_query, is_status_query
from geni_studio.hitl.service import GraphRunService, HitlError

router = APIRouter(tags=["feishu"])

_run_service: GraphRunService | None = None


def bind_run_service(service: GraphRunService) -> None:
    global _run_service
    _run_service = service


class OpenHitlBody(BaseModel):
    kind: str = Field(pattern="^(pm_clarification|escalation)$")
    questions: list[str] = Field(default_factory=list)
    summary: str = ""


class CardActionBody(BaseModel):
    thread_id: str
    gate_decision: str = Field(pattern="^(approved|rejected)$")
    human_reply: str = ""


def _webhook_authorized(request: Request) -> None:
    expected = os.environ.get("GENI_STUDIO_FEISHU_WEBHOOK_TOKEN", "").strip()
    if not expected:
        return
    got = request.headers.get("x-geni-studio-webhook-token", "")
    if not secrets.compare_digest(got, expected):
        raise HTTPException(status_code=401, detail="飞书回调未通过校验。")


def _awaiting_threads(svc: GraphRunService, candidates: list[str]) -> list[str]:
    waiting: list[str] = []
    for thread_id in candidates:
        try:
            st = svc.status(thread_id)
        except HitlError:
            continue
        if st.phase == "awaiting_human" and st.awaiting_human is not None:
            waiting.append(thread_id)
    return waiting


def _service() -> GraphRunService:
    if _run_service is None:
        raise HTTPException(status_code=503, detail="Run 服务未就绪")
    return _run_service


def _handle_im_message(body: dict) -> dict:
    im = parse_im_message_receive(body)
    if im is None:
        return {"ok": True, "ignored": "not_text_im"}
    text = im["text"]
    if is_status_query(text):
        return answer_status_query(
            service=_service(),
            chat_id=im.get("chat_id") or "",
            open_id=im.get("open_id") or "",
        )
    explicit = parse_thread_id_from_text(text)
    if explicit:
        thread_id = explicit
    else:
        waiting = _awaiting_threads(
            _service(),
            bound_thread_ids(chat_id=im.get("chat_id") or "", open_id=im.get("open_id") or ""),
        )
        if len(waiting) > 1:
            return {"ok": True, "ignored": "multiple_awaiting"}
        thread_id = waiting[0] if waiting else ""
    if not thread_id:
        return {"ok": True, "ignored": "no_thread_binding"}
    svc = _service()
    try:
        st = svc.status(thread_id)
    except HitlError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    if st.phase != "awaiting_human" or st.awaiting_human is None:
        return {"ok": True, "ignored": "not_awaiting_human"}
    ah = st.awaiting_human
    reply = normalize_im_hitl_reply(text)
    try:
        if ah.kind == "pm_clarification":
            st = svc.submit_hitl(thread_id, human_reply=reply, channel="feishu")
        elif ah.kind == "gate":
            decision = None
            if reply in ("批准", "通过", "approved", "LGTM", "ok"):
                decision = "approved"
            elif reply in ("驳回", "拒绝", "rejected"):
                decision = "rejected"
            if decision is None:
                return {"ok": True, "ignored": "gate_needs_decision_keyword"}
            st = svc.submit_hitl(
                thread_id,
                gate_decision=decision,
                human_reply=reply,
                channel="feishu",
            )
        elif ah.kind == "escalation":
            choice = reply.strip().lower()
            if choice not in ("continue", "pause", "abort"):
                mapping = {"继续": "continue", "暂停": "pause", "终止": "abort", "abort": "abort"}
                choice = mapping.get(reply, "")
            if choice not in ("continue", "pause", "abort"):
                return {"ok": True, "ignored": "escalation_needs_choice"}
            st = svc.submit_hitl(
                thread_id,
                escalation_choice=choice,  # type: ignore[arg-type]
                human_reply=reply,
                channel="feishu",
            )
        else:
            return {"ok": True, "ignored": ah.kind}
    except HitlError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    project_id = str(st.values.get("project_id") or "")
    notify_awaiting_human_via_lark_cli(svc, st.thread_id, project_id)
    return {"ok": True, "phase": st.phase, "thread_id": st.thread_id}


@router.post("/api/webhooks/feishu")
async def feishu_webhook(request: Request) -> dict[str, Any]:
    try:
        body = await request.json()
    except Exception as e:
        raise HTTPException(status_code=400, detail="无效 JSON") from e
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="请求体须为 object")

    challenge = url_verification_response(body)
    if challenge:
        return challenge
    _webhook_authorized(request)

    event_type = event_type_from_body(body)
    if event_type == "im.message.receive_v1":
        return _handle_im_message(body)

    event = extract_event_payload(body)
    if event_type != "card.action.trigger":
        event_type = str(
            event.get("type")
            or body.get("header", {}).get("event_type")
            or body.get("type")
            or event_type
            or ""
        )
    if event_type != "card.action.trigger":
        return {"ok": True, "ignored": event_type or "unknown"}

    svc = _service()
    try:
        action = parse_card_action_trigger(event if event else body)
    except FeishuInboundError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    settled = None
    if action.get("hitl_action") not in ("escalation", "pm_clarification"):
        try:
            before = svc.status(action["thread_id"])
        except HitlError:
            before = None
        if before is not None and before.awaiting_human is not None and before.awaiting_human.kind == "gate":
            label, reject_label = gate_presentation(before.values, before.awaiting_human.gate_id or "")
            if action.get("gate_decision") == "rejected" and reject_label:
                line = f"已记录：不通过，前往「{reject_label}」。"
            elif action.get("gate_decision") == "rejected":
                line = "已记录：不通过，本轮结束。"
            else:
                line = "已记录：批准。"
            settled = build_settled_gate_card(node_label=label, decision_line=line)

    try:
        if action.get("hitl_action") == "escalation":
            st = svc.submit_from_feishu_card(
                thread_id=action["thread_id"],
                escalation_choice=action["escalation_choice"],  # type: ignore[arg-type]
                human_reply=action.get("human_reply") or "",
            )
        elif action.get("hitl_action") == "pm_clarification":
            st = svc.submit_hitl(
                action["thread_id"],
                human_reply=action.get("human_reply") or "",
                channel="feishu",
            )
        else:
            st = svc.submit_from_feishu_card(
                thread_id=action["thread_id"],
                gate_decision=action["gate_decision"],  # type: ignore[arg-type]
                human_reply=action.get("human_reply") or "",
            )
    except HitlError as e:
        if "不在 awaiting_human" in str(e):
            return {
                **card_action_toast_response("这一轮已经不在等待批复。"),
                "ok": True,
                "ignored": "not_awaiting",
            }
        raise HTTPException(status_code=409, detail=str(e)) from e

    project_id = str(st.values.get("project_id") or "")
    notify_awaiting_human_via_lark_cli(svc, st.thread_id, project_id)
    payload = {
        **card_action_toast_response("已提交，工厂续跑中"),
        "ok": True,
        "phase": st.phase,
        "thread_id": st.thread_id,
    }
    if settled is not None:
        payload["card"] = {"type": "raw", "data": settled}
    return payload


@router.post("/api/webhooks/feishu/card-action")
def feishu_card_action_test(body: CardActionBody) -> dict[str, Any]:
    """本地/联调：模拟卡片 callback（无需公网 Webhook）。"""
    svc = _service()
    try:
        st = svc.submit_from_feishu_card(
            thread_id=body.thread_id,
            gate_decision=body.gate_decision,  # type: ignore[arg-type]
            human_reply=body.human_reply,
        )
    except HitlError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    project_id = str(st.values.get("project_id") or "")
    notify_awaiting_human_via_lark_cli(svc, st.thread_id, project_id)
    return svc.status_dict(st.thread_id)


@router.post("/api/runs/{thread_id}/hitl/open")
def api_open_hitl(thread_id: str, body: OpenHitlBody) -> dict:
    svc = _service()
    try:
        st = svc.open_hitl(
            thread_id,
            kind=body.kind,  # type: ignore[arg-type]
            questions=body.questions,
            summary=body.summary,
        )
    except HitlError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    project_id = str(st.values.get("project_id") or "")
    notify_awaiting_human_via_lark_cli(svc, thread_id, project_id)
    return svc.status_dict(thread_id)
