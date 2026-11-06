"""default 工作流图中可裁剪的节点名（与 default.py 当前注册名一致）。

财务三个节点暂未注册。函数保留在 workflows/default.py 的
_FINANCE_NODES_RESERVED，接回图之后再加入本集合。
"""

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
    }
)
