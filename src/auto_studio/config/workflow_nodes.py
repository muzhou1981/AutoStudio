"""default 工作流图中可裁剪的节点名（与 default.py 注册名一致）。"""

DEFAULT_GRAPH_NODES = frozenset(
    {
        "project_manager_draft",
        "tester_testability",
        "gate_requirement_confirm",
        "ux_designer",
        "ui_designer",
        "visual_designer",
        "config_manager_plan",
        "finance_budget_rough",
        "project_manager_scope",
        "architect",
        "finance_budget_final",
        "gate_architecture_review",
        "developer",
        "code_reviewer",
        "tester_execute",
        "qa",
        "finance_cost_snapshot",
        "project_manager_delivery",
        "gate_final_delivery",
        "config_manager_closeout",
        "process_owner_retro",
        "escalate_dev_retry",
    }
)
