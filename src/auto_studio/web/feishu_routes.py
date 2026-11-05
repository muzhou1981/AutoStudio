"""飞书入站 Webhook / 卡片回调。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from auto_studio.hitl.feishu_inbound import (
    FeishuInboundError,
    extract_event_payload,
    parse_card_action_trigger,
    url_verification_response,
)
from auto_studio.hitl.feishu_notify import notify_awaiting_human_via_lark_cli
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

    event = extract_event_payload(body)
    event_type = str(
        event.get("type")
        or body.get("header", {}).get("event_type")
        or body.get("type")
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
        st = svc.submit_from_feishu_card(
            thread_id=action["thread_id"],
            gate_decision=action["gate_decision"],  # type: ignore[arg-type]
            human_reply=action.get("human_reply") or "",
        )
    except HitlError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    project_id = str(st.values.get("project_id") or "")
    notify_awaiting_human_via_lark_cli(svc, st.thread_id, project_id)
    return {"ok": True, "phase": st.phase, "thread_id": st.thread_id}


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
        svc.open_hitl(
            thread_id,
            kind=body.kind,  # type: ignore[arg-type]
            questions=body.questions,
            summary=body.summary,
        )
    except HitlError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return svc.status_dict(thread_id)
