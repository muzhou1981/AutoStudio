"""Run 进入 awaiting_human 时经 lark-cli 推送 PM 通知（文本或交互卡片）。"""

from __future__ import annotations

import logging
import os

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


def notify_awaiting_human_via_lark_cli(
    service: GraphRunService,
    thread_id: str,
    project_id: str,
) -> bool:
    cfg = load_feishu_hitl_config(project_id)
    if cfg is None or cfg.backend != "lark_cli":
        return False
    summary = auth_summary()
    if not summary.bot_ready:
        logger.warning("跳过飞书通知：lark-cli 未就绪 — %s", summary.hint)
        return False
    try:
        st = service.status(thread_id)
    except HitlError:
        return False
    if st.phase != "awaiting_human" or st.awaiting_human is None:
        return False
    ah = st.awaiting_human
    web_url = _web_url(cfg, thread_id)
    try:
        if ah.kind == "gate" and _use_interactive_card():
            card = build_gate_interactive_card(
                thread_id=thread_id,
                summary=ah.summary,
                gate_id=ah.gate_id,
                web_url=web_url,
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
    except LarkCliError as e:
        logger.warning("飞书通知发送失败：%s", e)
        return False
    register_awaiting_thread(
        thread_id=thread_id,
        chat_id=cfg.notify_chat_id,
        open_id=cfg.notify_open_id,
    )
    return True
