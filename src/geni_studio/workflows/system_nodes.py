"""系统节点与路由条件：流程文件以名称引用，编译器在运行时解析。"""

from __future__ import annotations

from typing import Any

# 节点实现在 workflows/default.py；按名称在调用时查找，便于测试替换。
HANDLERS = frozenset(
    {
        "project_manager_draft",
        "pm_clarification_check",
        "hitl_pause",
        "tester_testability",
        "config_manager_plan",
        "ux_designer",
        "ui_designer",
        "visual_designer",
        "finance_budget_rough",
        "project_manager_scope",
        "architect",
        "finance_budget_final",
        "developer",
        "change_control",
        "code_reviewer",
        "tester_execute",
        "qa",
        "finance_cost_snapshot",
        "project_manager_delivery",
        "config_manager_closeout",
        "process_owner_retro",
        "escalate_dev_retry",
    }
)

_FEATURES = frozenset({"design_track", "finance"})
_PREFIXES = ("feature:", "pending:", "impact:", "failed:", "false:", "not:")


def handler(name: str):
    from geni_studio.workflows import default

    return getattr(default, name)


def condition_problem(cond: Any) -> str:
    """条件写法不合法时返回说明，合法时返回空串。"""
    items = cond if isinstance(cond, list) else [cond]
    if not items:
        return "条件不能为空。"
    for item in items:
        text = str(item or "").strip()
        text = text.removeprefix("not:")
        if text == "retries_exhausted":
            continue
        if text.startswith("feature:"):
            if text[8:] not in _FEATURES:
                return f"未知的开关：{text}。"
            continue
        if not text.startswith(_PREFIXES) or ":" not in text or not text.split(":", 1)[1]:
            return f"无法识别的条件：{item}。"
    return ""


def evaluate(cond: Any, state: dict[str, Any]) -> bool:
    items = cond if isinstance(cond, list) else [cond]
    return all(_one(str(item).strip(), state) for item in items)


def _one(text: str, state: dict[str, Any]) -> bool:
    from geni_studio.workflows import default

    if text.startswith("not:"):
        return not _one(text[4:], state)
    if text == "retries_exhausted":
        return int(state.get("dev_retry_count") or 0) >= default.max_dev_retries_for_state(state)
    kind, _, arg = text.partition(":")
    if kind == "feature":
        if arg == "finance":
            return bool(default._finance_enabled(state))
        if "design_track_enabled" in state:
            return bool(state.get("design_track_enabled"))
        return bool(default.resolve_design_track_enabled(state))
    if kind == "pending":
        return state.get("hitl_pending_kind") == arg
    if kind == "impact":
        return (state.get("change_impact") or "") == arg
    if kind == "failed":
        return state.get(arg) == "fail"
    if kind == "false":
        return state.get(arg) is False
    return False
