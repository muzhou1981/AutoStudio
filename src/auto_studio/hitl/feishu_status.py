"""飞书状态查询：固定四行，不触发批准或驳回。"""

from __future__ import annotations

from auto_studio.hitl.feishu_cards import (
    build_status_interactive_card,
    card_content_json,
)
from auto_studio.hitl.feishu_notify import hitl_page_url
from auto_studio.hitl.feishu_session import bound_thread_ids
from auto_studio.hitl.lark_cli_client import LarkCliError, send_interactive_as_bot
from auto_studio.hitl.rail import label_for
from auto_studio.hitl.service import GraphRunService, HitlError

_STATUS_QUERIES = frozenset({"状态", "到哪了", "到哪", "进度", "status"})
_OPEN_PHASES = frozenset({"running", "awaiting_human", "paused"})
_PHASE_LABEL = {
    "idle": "未启动",
    "running": "运行中",
    "awaiting_human": "等待人工",
    "paused": "已暂停",
    "completed": "已完成",
    "rejected": "已驳回",
    "stopped": "已停止",
}


def is_status_query(text: str) -> bool:
    """整句去空白后命中查询词。不把带前后缀的句子当成查询。"""
    normalized = text.strip()
    if not normalized:
        return False
    if normalized.lower() == "status":
        return True
    return normalized in _STATUS_QUERIES


def _current_label(rail: dict) -> str:
    current = str(rail.get("current") or "")
    cells = rail.get("cells") or []
    if current:
        for cell in cells:
            if cell.get("id") == current:
                return str(cell.get("label") or label_for(current))
        return label_for(current)
    done = [cell for cell in cells if cell.get("state") == "done"]
    if done:
        return str(done[-1].get("label") or "")
    return "无"


def _todo_line(awaiting: dict | None, current_label: str) -> str:
    if not awaiting:
        return "无"
    kind = str(awaiting.get("kind") or "")
    name = current_label if current_label and current_label != "无" else "当前节点"
    if kind == "gate":
        return f"待批复 · {name}"
    if kind == "pm_clarification":
        return f"待澄清 · {name}"
    if kind == "escalation":
        return f"待决策 · {name}"
    return "无"


def status_lines_for_thread(service: GraphRunService, thread_id: str, web_url: str) -> list[str]:
    data = service.status_dict(thread_id)
    phase = str(data.get("phase") or "")
    rail = data.get("rail") or {}
    current = _current_label(rail)
    lines = [
        f"阶段：{_PHASE_LABEL.get(phase, phase or '未启动')}",
        f"当前：{current}",
        f"待办：{_todo_line(data.get('awaiting_human'), current)}",
    ]
    if web_url:
        lines.append(f"打开：{web_url}")
    return lines


def empty_status_lines() -> list[str]:
    return [
        "阶段：未启动",
        "当前：还没有进行中的轮次",
        "待办：无",
    ]


def pick_status_thread(service: GraphRunService, thread_ids: list[str]) -> str | None:
    """优先最近一轮仍在运行、已暂停或等待人工的；否则回答最近一轮已知记录。"""
    latest_known: str | None = None
    for thread_id in thread_ids:
        try:
            status = service.status(thread_id)
        except HitlError:
            continue
        if latest_known is None:
            latest_known = thread_id
        if status.phase in _OPEN_PHASES:
            return thread_id
    return latest_known


def deliver_status_card(*, chat_id: str, open_id: str, card_json: str) -> bool:
    if not chat_id and not open_id:
        return False
    try:
        if chat_id:
            send_interactive_as_bot(chat_id=chat_id, content_json=card_json)
        else:
            send_interactive_as_bot(open_id=open_id, content_json=card_json)
    except LarkCliError:
        return False
    return True


def answer_status_query(
    *,
    service: GraphRunService,
    chat_id: str = "",
    open_id: str = "",
    web_base: str = "",
) -> dict:
    from auto_studio.hitl.feishu_config import resolve_public_base_url

    thread_id = pick_status_thread(
        service,
        bound_thread_ids(chat_id=chat_id, open_id=open_id),
    )
    base = (web_base or resolve_public_base_url()).rstrip("/")
    web_url = hitl_page_url(base, thread_id) if thread_id else ""
    if thread_id:
        try:
            lines = status_lines_for_thread(service, thread_id, web_url)
        except HitlError:
            lines = empty_status_lines()
            web_url = ""
            thread_id = ""
    else:
        lines = empty_status_lines()
    card = build_status_interactive_card(lines=lines, web_url=web_url)
    sent = deliver_status_card(
        chat_id=chat_id,
        open_id=open_id,
        card_json=card_content_json(card),
    )
    return {
        "ok": True,
        "status_query": True,
        "sent": sent,
        "thread_id": thread_id or "",
        "lines": lines,
    }
