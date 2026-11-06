"""人工处理页的节点轨道。

进度只根据已知节点清单、下一节点和场景裁剪计算，不估计剩余时间。
"""

from __future__ import annotations

import re
from typing import Any

# 主路径。内部节点 pm_clarification_check / hitl_pause 不占格。
# run_start / run_end 只作轨道上的初始与最终状态，不进入可执行图。
RAIL_NODES: tuple[tuple[str, str], ...] = (
    ("run_start", "启动"),
    ("project_manager_draft", "项目经理起草"),
    ("tester_testability", "可测性"),
    ("gate_requirement_confirm", "需求确认"),
    ("config_manager_plan", "配置计划"),
    ("ux_designer", "体验"),
    ("ui_designer", "界面"),
    ("visual_designer", "视觉"),
    ("finance_budget_rough", "预算粗估"),
    ("project_manager_scope", "范围"),
    ("architect", "架构"),
    ("finance_budget_final", "预算"),
    ("gate_architecture_review", "架构评审"),
    ("developer", "开发"),
    ("change_control", "变更"),
    ("code_reviewer", "评审"),
    ("tester_execute", "测试"),
    ("qa", "质量门禁"),
    ("finance_cost_snapshot", "成本快照"),
    ("project_manager_delivery", "交付汇总"),
    ("gate_final_delivery", "最终交付"),
    ("config_manager_closeout", "收口"),
    ("process_owner_retro", "复盘"),
    ("run_end", "结束"),
)

_RAIL_MARKERS = frozenset({"run_start", "run_end"})

RAIL_INDEX = {name: i for i, (name, _) in enumerate(RAIL_NODES)}

# 检视时读取的产物字段。成本行按角色过滤，关卡不挂成本。
NODE_ARTIFACTS: dict[str, tuple[str, ...]] = {
    "project_manager_draft": ("requirement_spec",),
    "tester_testability": ("testability_review",),
    "gate_requirement_confirm": ("requirement_spec",),
    "config_manager_plan": ("config_plan",),
    "ux_designer": ("ux_spec",),
    "ui_designer": ("ui_spec",),
    "visual_designer": ("visual_assets",),
    "finance_budget_rough": ("budget_plan",),
    "project_manager_scope": ("requirement_spec",),
    "architect": ("architecture_design", "task_plan"),
    "finance_budget_final": ("budget_plan",),
    "gate_architecture_review": ("architecture_design", "task_plan"),
    "developer": ("code_change",),
    "change_control": ("change_request",),
    "code_reviewer": ("review_report",),
    "tester_execute": ("test_report", "test_cases"),
    "qa": ("qa_report",),
    "finance_cost_snapshot": ("cost_report", "cost_ledger"),
    "project_manager_delivery": ("delivery_report",),
    "gate_final_delivery": ("delivery_report", "qa_report"),
    "config_manager_closeout": ("baseline_log", "config_baseline"),
    "process_owner_retro": ("retro_report",),
}

NODE_ROLE: dict[str, str] = {
    "project_manager_draft": "project_manager",
    "project_manager_scope": "project_manager",
    "project_manager_delivery": "project_manager",
    "tester_testability": "tester",
    "tester_execute": "tester",
    "config_manager_plan": "config_manager",
    "config_manager_closeout": "config_manager",
    "ux_designer": "ux_designer",
    "ui_designer": "ui_designer",
    "visual_designer": "visual_designer",
    "finance_budget_rough": "finance",
    "finance_budget_final": "finance",
    "finance_cost_snapshot": "finance",
    "architect": "architect",
    "developer": "developer",
    "code_reviewer": "code_reviewer",
    "qa": "qa",
    "process_owner_retro": "process_owner",
}

_INTERNAL_TO_RAIL = {
    "pm_clarification_check": "project_manager_draft",
    "hitl_pause": "project_manager_draft",
    "escalate_dev_retry": "developer",
}

_BASELINE_GATE = re.compile(r"^\[baseline:([^\]]+)\].*decision=rejected")


def label_for(node_id: str) -> str:
    for name, label in RAIL_NODES:
        if name == node_id:
            return label
    return node_id


def rejected_gate_id(baseline_log: str) -> str | None:
    found: str | None = None
    for line in (baseline_log or "").splitlines():
        match = _BASELINE_GATE.match(line.strip())
        if match:
            found = match.group(1)
    return found


def build_rail(
    *,
    phase: str,
    next_nodes: list[str] | tuple[str, ...],
    awaiting: dict[str, Any] | None,
    skip_nodes: set[str] | None,
    baseline_log: str = "",
    stopped_at: str = "",
    paused_at: str = "",
) -> dict[str, Any]:
    """返回轨道。skip_nodes 为 None 表示还不知道场景裁剪，此时不给出完成计数。"""
    current = _current_node(
        phase,
        next_nodes,
        awaiting,
        baseline_log,
        stopped_at=stopped_at,
        paused_at=paused_at,
    )
    current_index = RAIL_INDEX.get(current) if current else None
    known_skip = skip_nodes is not None
    skipped = skip_nodes or set()

    cells: list[dict[str, Any]] = []
    done = 0
    runnable = 0
    for index, (name, label) in enumerate(RAIL_NODES):
        if known_skip and name in skipped and name not in _RAIL_MARKERS:
            state = "skipped"
        elif phase == "stopped":
            if current_index is None or index > current_index:
                state = "pending"
            elif index < current_index:
                state = "done"
            else:
                state = "stopped"
        elif phase == "paused":
            if current_index is None or index > current_index:
                state = "pending"
            elif index < current_index:
                state = "done"
            else:
                state = "paused"
        elif current_index is None:
            state = "pending"
        elif index < current_index:
            state = "done"
        elif index == current_index:
            if phase in {"idle", ""}:
                state = "initial"
            elif phase == "completed":
                state = "finished"
            elif phase in {"awaiting_human", "rejected"}:
                state = "waiting"
            else:
                state = "active"
        else:
            state = "pending"
        if state != "skipped":
            runnable += 1
        if state == "done":
            done += 1
        cells.append(
            {
                "id": name,
                "label": label,
                "state": state,
                "artifacts": list(NODE_ARTIFACTS.get(name, ())),
                "role": NODE_ROLE.get(name, ""),
            }
        )

    return {
        "cells": cells,
        "current": current,
        "done": done if known_skip else None,
        "total": runnable if known_skip else None,
    }


def _current_node(
    phase: str,
    next_nodes: list[str] | tuple[str, ...],
    awaiting: dict[str, Any] | None,
    baseline_log: str,
    *,
    stopped_at: str = "",
    paused_at: str = "",
) -> str | None:
    if phase == "stopped":
        if stopped_at in RAIL_INDEX:
            return stopped_at
        return None
    if phase == "paused":
        if paused_at in RAIL_INDEX:
            return paused_at
        if next_nodes and next_nodes[0] in RAIL_INDEX:
            return next_nodes[0]
        return None
    if phase in {"idle", ""}:
        return "run_start"
    if phase == "completed":
        return "run_end"
    if awaiting:
        kind = str(awaiting.get("kind") or "")
        if kind == "pm_clarification":
            return "project_manager_draft"
        if kind == "escalation":
            return "developer"
        if kind == "gate":
            gate_id = str(awaiting.get("gate_id") or "")
            if gate_id in RAIL_INDEX:
                return gate_id
    if phase == "rejected":
        gate_id = rejected_gate_id(baseline_log)
        if gate_id in RAIL_INDEX:
            return gate_id
        return None
    if not next_nodes:
        return None
    head = next_nodes[0]
    mapped = _INTERNAL_TO_RAIL.get(head, head)
    if mapped in RAIL_INDEX:
        return mapped
    return None
