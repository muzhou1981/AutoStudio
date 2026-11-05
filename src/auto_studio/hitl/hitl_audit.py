"""HITL 提交审计（写入 state.run_record / hitl_audit_log）。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def append_hitl_audit(
    existing: str,
    *,
    channel: str,
    kind: str,
    thread_id: str,
    summary: str = "",
    gate_decision: str | None = None,
    human_reply: str = "",
) -> str:
    ts = datetime.now(UTC).isoformat()
    parts = [f"[hitl {ts}]", f"channel={channel}", f"kind={kind}", f"thread={thread_id}"]
    if gate_decision:
        parts.append(f"gate_decision={gate_decision}")
    if summary:
        parts.append(f"summary={summary[:200]}")
    if human_reply:
        parts.append(f"reply={human_reply[:500]}")
    line = " ".join(parts)
    if not existing.strip():
        return line
    return existing.rstrip() + "\n" + line


def audit_patch(
    values: dict[str, Any],
    *,
    channel: str,
    kind: str,
    thread_id: str,
    summary: str = "",
    gate_decision: str | None = None,
    human_reply: str = "",
) -> dict[str, str]:
    prev = str(values.get("hitl_audit_log") or values.get("run_record") or "")
    log = append_hitl_audit(
        prev,
        channel=channel,
        kind=kind,
        thread_id=thread_id,
        summary=summary,
        gate_decision=gate_decision,
        human_reply=human_reply,
    )
    return {"hitl_audit_log": log, "run_record": log}
