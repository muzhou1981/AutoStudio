"""Run 进入 awaiting_human 时经 lark-cli 推送 PM 通知（文本或交互卡片）。"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from geni_studio.hitl.feishu_cards import (
    build_escalation_interactive_card,
    build_gate_interactive_card,
    build_pm_clarification_interactive_card,
    card_content_json,
)
from geni_studio.hitl.feishu_config import (
    FeishuHitlConfig,
    load_feishu_hitl_config,
    resolve_public_base_url,
)
from geni_studio.hitl.feishu_session import register_awaiting_thread
from geni_studio.hitl.lark_cli_client import (
    LarkCliError,
    auth_summary,
    send_interactive_as_bot,
    send_text_as_bot,
)
from geni_studio.hitl.service import GraphRunService, HitlError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NotifyResult:
    sent: bool
    detail: str = ""


def gate_presentation(values: dict, gate_id: str) -> tuple[str, str]:
    """返回决策点显示名，以及不通过时前往的节点名。后者为空表示结束本轮。"""
    from geni_studio.hitl.rail import label_for

    nodes = values.get("workflow_nodes") if isinstance(values.get("workflow_nodes"), list) else []
    by_id = {
        str(item.get("id") or ""): item
        for item in nodes
        if isinstance(item, dict)
    }
    current = by_id.get(gate_id) or {}
    label = str(current.get("label") or "").strip() or label_for(gate_id)
    reject_id = str(current.get("reject_to") or "").strip()
    reject_label = ""
    if reject_id:
        target = by_id.get(reject_id) or {}
        reject_label = str(target.get("label") or "").strip() or label_for(reject_id)
    return label, reject_label


def gate_excerpt(values: dict, gate_id: str, summary: str) -> str:
    from geni_studio.hitl.reading import human_reading

    sections = human_reading(
        {"kind": "gate", "gate_id": gate_id, "summary": summary},
        values,
    )
    if not sections:
        request = str(values.get("human_request") or "").strip()
        if request:
            sections = [{"title": "交付目标", "body": request[:400]}]
    parts: list[str] = []
    budget = 900
    for section in sections[:3]:
        body = str(section.get("body") or "").strip()
        if len(body) > 280:
            body = body[:280] + "…"
        line = f"**{section.get('title') or '说明'}**\n{body}"
        if len(line) > budget:
            break
        parts.append(line)
        budget -= len(line)
    return "\n\n".join(parts)


def _use_interactive_card() -> bool:
    raw = os.environ.get("GENI_STUDIO_FEISHU_USE_CARD", "1").strip().lower()
    return raw not in ("0", "false", "no")


def hitl_page_url(base: str, thread_id: str) -> str:
    root = base.rstrip("/")
    return f"{root}/?thread_id={thread_id}"


def _web_url(cfg: FeishuHitlConfig, thread_id: str) -> str:
    base = cfg.web_base_url or resolve_public_base_url()
    return hitl_page_url(base, thread_id)


def format_gate_message(
    *,
    thread_id: str,
    summary: str,
    gate_id: str | None,
    web_url: str,
) -> str:
    from geni_studio.hitl.rail import label_for

    label = label_for(gate_id) if gate_id else ""
    lines = [
        "【软件工厂 · 项目经理】",
        "阶段：等待人工",
        f"Run：{thread_id}",
    ]
    if label:
        lines.append(f"当前：{label}")
        lines.append(f"待办：待批复 · {label}")
    if summary:
        lines.append(summary)
    lines.append(f"打开：{web_url}")
    return "\n".join(lines)


def _send_to_target(cfg: FeishuHitlConfig, *, text: str = "", card_json: str = "") -> None:
    if cfg.backend == "env_bot":
        _send_via_tenant(cfg, text=text, card_json=card_json)
        return
    if card_json:
        if cfg.notify_chat_id:
            send_interactive_as_bot(chat_id=cfg.notify_chat_id, content_json=card_json)
        else:
            send_interactive_as_bot(open_id=cfg.notify_open_id, content_json=card_json)
    elif text:
        if cfg.notify_chat_id:
            send_text_as_bot(chat_id=cfg.notify_chat_id, text=text)
        else:
            send_text_as_bot(open_id=cfg.notify_open_id, text=text)


def _send_via_tenant(cfg: FeishuHitlConfig, *, text: str, card_json: str) -> None:
    import os

    from geni_studio.hitl.feishu_open_api import send_interactive_via_tenant

    app_id = os.environ.get("LARK_APP_ID", "").strip()
    app_secret = os.environ.get("LARK_APP_SECRET", "").strip()
    if not app_id or not app_secret:
        raise LarkCliError("飞书应用凭据未配置。")
    content = card_json
    if not content and text:
        content = card_content_json(
            {
                "schema": "2.0",
                "body": {
                    "elements": [{"tag": "markdown", "content": text}],
                },
            }
        )
    send_interactive_via_tenant(
        app_id=app_id,
        app_secret=app_secret,
        content_json=content,
        chat_id=cfg.notify_chat_id,
        open_id=cfg.notify_open_id,
    )


def notify_awaiting_human_via_lark_cli(
    service: GraphRunService,
    thread_id: str,
    project_id: str,
) -> NotifyResult:
    cfg = load_feishu_hitl_config(project_id)
    if cfg is None:
        return NotifyResult(False, "")
    if cfg.backend == "lark_cli":
        summary = auth_summary()
        if not summary.bot_ready:
            logger.warning("跳过飞书通知：lark-cli 未就绪 — %s", summary.hint)
            return NotifyResult(False, summary.hint or "lark-cli 未就绪。")
    try:
        st = service.status(thread_id)
    except HitlError:
        return NotifyResult(False, "")
    if st.phase != "awaiting_human" or st.awaiting_human is None:
        return NotifyResult(False, "")
    ah = st.awaiting_human
    web_url = _web_url(cfg, thread_id)
    status = service.status_dict(thread_id)
    choices = status.get("choices") if isinstance(status.get("choices"), list) else []
    try:
        if ah.kind == "gate" and _use_interactive_card():
            label, reject_label = gate_presentation(st.values, ah.gate_id or "")
            card = build_gate_interactive_card(
                thread_id=thread_id,
                summary=ah.summary,
                gate_id=ah.gate_id,
                web_url=web_url,
                node_label=label,
                reject_label=reject_label,
                excerpt=gate_excerpt(st.values, ah.gate_id or "", ah.summary),
                choices=choices,
            )
            _send_to_target(cfg, card_json=card_content_json(card))
        elif ah.kind == "escalation" and _use_interactive_card():
            card = build_escalation_interactive_card(
                thread_id=thread_id,
                summary=ah.summary,
                web_url=web_url,
            )
            _send_to_target(cfg, card_json=card_content_json(card))
        elif ah.kind == "pm_clarification" and _use_interactive_card():
            card = build_pm_clarification_interactive_card(
                thread_id=thread_id,
                summary=ah.summary,
                questions=ah.questions,
                web_url=web_url,
                choices=choices,
            )
            _send_to_target(cfg, card_json=card_content_json(card))
        else:
            msg = format_gate_message(
                thread_id=thread_id,
                summary=ah.summary,
                gate_id=ah.gate_id,
                web_url=web_url,
            )
            if ah.kind != "gate" and ah.questions:
                msg += "\n待答：" + "；".join(ah.questions)
            _send_to_target(cfg, text=msg)
    except LarkCliError as exc:
        logger.warning("飞书通知发送失败：%s", exc)
        return NotifyResult(False, str(exc))
    register_awaiting_thread(
        thread_id=thread_id,
        chat_id=cfg.notify_chat_id,
        open_id=cfg.notify_open_id,
    )
    return NotifyResult(True, "")
