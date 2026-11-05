"""飞书入站 Webhook / 卡片回调。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from auto_studio.hitl.feishu_inbound import (
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
from auto_studio.hitl.feishu_notify import notify_awaiting_human_via_lark_cli
from auto_studio.hitl.feishu_session import resolve_thread_id
from auto_studio.hitl.service import GraphRunService, HitlError

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


def _service() -> GraphRunService:
    if _run_service is None:
        raise HTTPException(status_code=503, detail="Run 服务未就绪")
    return _run_service


def _handle_im_message(body: dict) -> dict:
    im = parse_im_message_receive(body)
    if im is None:
        return {"ok": True, "ignored": "not_text_im"}
    text = im["text"]
    thread_id = parse_thread_id_from_text(text) or resolve_thread_id(
        chat_id=im.get("chat_id") or "",
        open_id=im.get("open_id") or "",
    )
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

    try:
        if action.get("hitl_action") == "escalation":
            st = svc.submit_from_feishu_card(
                thread_id=action["thread_id"],
                escalation_choice=action["escalation_choice"],  # type: ignore[arg-type]
                human_reply=action.get("human_reply") or "",
            )
        else:
            st = svc.submit_from_feishu_card(
                thread_id=action["thread_id"],
                gate_decision=action["gate_decision"],  # type: ignore[arg-type]
                human_reply=action.get("human_reply") or "",
            )
    except HitlError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    project_id = str(st.values.get("project_id") or "")
    notify_awaiting_human_via_lark_cli(svc, st.thread_id, project_id)
    return {
        **card_action_toast_response("已提交，工厂续跑中"),
        "ok": True,
        "phase": st.phase,
        "thread_id": st.thread_id,
    }


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
