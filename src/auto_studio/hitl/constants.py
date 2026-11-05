"""人工关卡节点与展示文案。"""

GATE_NODES = frozenset(
    {
        "gate_requirement_confirm",
        "gate_architecture_review",
        "gate_final_delivery",
    }
)

_GATE_SUMMARIES: dict[str, str] = {
    "gate_requirement_confirm": "需求确认：请批准或驳回当前需求说明与可测试性结论。",
    "gate_architecture_review": "架构评审：请批准或驳回架构设计、任务计划与正式预算。",
    "gate_final_delivery": "最终交付：请批准或驳回交付报告与验证证据。",
}


def gate_summary(gate_id: str) -> str:
    return _GATE_SUMMARIES.get(gate_id, f"人工关卡：{gate_id}")
