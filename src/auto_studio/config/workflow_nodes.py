"""default 工作流图中可裁剪的节点名（与 default.py 当前注册名一致）。"""

FINANCE_NODES = frozenset(
    {
        "finance_budget_rough",
        "finance_budget_final",
        "finance_cost_snapshot",
    }
)

DEFAULT_GRAPH_NODES = frozenset(
    {
        "project_manager_draft",
        "tester_testability",
        "gate_requirement_confirm",
        "ux_designer",
        "ui_designer",
        "visual_designer",
        "config_manager_plan",
        "project_manager_scope",
        "architect",
        "gate_architecture_review",
        "developer",
        "change_control",
        "code_reviewer",
        "tester_execute",
        "qa",
        "project_manager_delivery",
        "gate_final_delivery",
        "config_manager_closeout",
        "process_owner_retro",
        "escalate_dev_retry",
        *FINANCE_NODES,
    }
)
