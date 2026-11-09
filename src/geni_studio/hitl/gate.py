"""关卡节点共用逻辑。"""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from geni_studio.workflows.default import FactoryState

GateDecision = str


def apply_gate_node(gate_id: str, state: "FactoryState") -> dict:
    """读取 ``gate_decision`` / ``human_reply``，写入 ``baseline_log`` 与 ``last_gate_decision``。"""
    decision = state.get("gate_decision") or "approved"
    if decision not in ("approved", "rejected"):
        decision = "approved"
    note = (state.get("human_reply") or "").strip()
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    entry = (
        f"[baseline:{gate_id}] decision={decision} at={ts}"
        + (f" note={note!r}" if note else "")
    )
    prior = (state.get("baseline_log") or "").strip()
    log = f"{prior}\n{entry}".strip() if prior else entry
    cleared: dict = {
        "baseline_log": log,
        "last_gate_decision": decision,
        "human_reply": "",
        "awaiting_since": "",
        "gate_timeout_recorded": False,
        "gate_timeout_note": "",
    }
    impact = str(state.get("change_impact") or "")
    resolves = (gate_id == "gate_requirement_confirm" and impact == "scope") or (
        gate_id == "gate_architecture_review" and impact == "architecture"
    )
    if decision == "approved" and resolves:
        cleared["change_request"] = ""
        cleared["change_impact"] = ""
    return cleared
