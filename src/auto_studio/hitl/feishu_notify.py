"""Run 进入 awaiting_human 时经 lark-cli 推送 PM 通知。"""

from __future__ import annotations

import logging

from auto_studio.hitl.feishu_config import (
    FeishuHitlConfig,
    load_feishu_hitl_config,
    resolve_public_base_url,
)
from auto_studio.hitl.lark_cli_client import (
    LarkCliError,
    auth_summary,
    send_text_as_bot,
)
from auto_studio.hitl.service import GraphRunService, HitlError

logger = logging.getLogger(__name__)


def _web_url(cfg: FeishuHitlConfig, thread_id: str) -> str:
    base = (cfg.web_base_url or resolve_public_base_url()).rstrip("/")
    return f"{base}/?thread={thread_id}"


def format_gate_message(
    *,
    thread_id: str,
    summary: str,
    gate_id: str | None,
    web_url: str,
) -> str:
    lines = [
        "【软件工厂 · 项目经理】",
        f"Run：{thread_id}",
    ]
    if gate_id:
        lines.append(f"关卡：{gate_id}")
    if summary:
        lines.append(summary)
    lines.append(f"请在 Web 批复（批准/驳回）：{web_url}")
    lines.append("（飞书交互卡片与按钮回调后续接入；当前以 Web 为准。）")
    return "\n".join(lines)


def notify_awaiting_human_via_lark_cli(
    service: GraphRunService,
    thread_id: str,
    project_id: str,
) -> bool:
    """若配置齐全且处于 awaiting_human，发送 Bot 文本通知。成功返回 True。"""
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
    msg = format_gate_message(
        thread_id=thread_id,
        summary=ah.summary,
        gate_id=ah.gate_id,
        web_url=_web_url(cfg, thread_id),
    )
    try:
        if cfg.notify_chat_id:
            send_text_as_bot(chat_id=cfg.notify_chat_id, text=msg)
        else:
            send_text_as_bot(open_id=cfg.notify_open_id, text=msg)
    except LarkCliError as e:
        logger.warning("飞书通知发送失败：%s", e)
        return False
    return True
