"""auto_studio 默认工作流程（第一版骨架）。

节点当前为占位实现：只更新图状态中的产物字段，便于在 LangGraph Studio 中联调结构与关卡。
后续在各节点内接入角色定义（roles/）与后端插件（backends/）。
"""

from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from auto_studio.config.context import (
    ConfigError,
    build_run_context_from_state,
    resolve_design_track,
)
from auto_studio.hitl.gate import apply_gate_node
from auto_studio.workflows.node_wrap import skip_if_disabled
from auto_studio.workspace.checkpoint import default_checkpointer

# 无有效 project/scenario 配置时的回退上限
DEFAULT_MAX_DEV_RETRIES = 3

ReviewStatus = Literal["pass", "fail"]
TestStatus = Literal["pass", "fail"]
QaStatus = Literal["pass", "fail"]
GateDecision = Literal["approved", "rejected"]


class FactoryState(TypedDict, total=False):
    """与 roles/*/role.md 中产物名对齐；值为占位字符串，接入 Agent 后改为结构化产物。"""

    # 引擎 / 人类输入
    human_request: str
    scenario_key: str
    project_id: str
    run_name: str
    design_track_enabled: bool
    cost_ledger: str
    run_record: str

    # 项目经理
    requirement_spec: str
    delivery_report: str

    # 测试工程师
    testability_review: str
    test_cases: str
    test_report: str

    # 配置管理员
    config_plan: str
    baseline_log: str
    config_baseline: str
    config_retro: str

    # 财务
    budget_plan: str
    cost_report: str

    # UX / UI / 美工
    ux_spec: str
    ui_spec: str
    visual_assets: str

    # 架构师
    architecture_design: str
    task_plan: str

    # 程序员 / 变更
    code_change: str
    change_request: str

    # 代码评审 / QA
    review_report: str
    qa_report: str

    # 复盘
    retro_report: str
    process_proposals: str
    config_proposals: str

    # 流程控制（占位节点写入；Studio 调试时可手动改 state 测分支）
    review_status: ReviewStatus
    test_status: TestStatus
    qa_status: QaStatus
    dev_retry_count: int
    budget_phase: Literal["rough", "final", "snapshot"]

    # HITL（ADR 0003）；关卡前 interrupt，人类经 Web/飞书写入后 Resume
    gate_decision: GateDecision
    human_reply: str
    last_gate_decision: GateDecision
    hitl_pending_kind: str
    hitl_questions: list[str]
    hitl_summary: str
    hitl_pending_since: str
    hitl_audit_log: str
    escalation_choice: str
    hitl_clarification_resolved: bool
    workspace_path: str
    test_command: str
    change_impact: str
    change_baseline_note: str
    delivery_ready: bool
    run_stopped: bool
    stopped_at: str
    run_paused: bool
    paused_at: str


def _touch_artifact(state: FactoryState, key: str, role: str, note: str) -> dict:
    return {key: f"[stub:{role}] {note}"}


def _run_context_or_none(state: FactoryState):
    try:
        return build_run_context_from_state(state)
    except ConfigError:
        return None


def max_dev_retries_for_state(state: FactoryState) -> int:
    ctx = _run_context_or_none(state)
    if ctx is None:
        return DEFAULT_MAX_DEV_RETRIES
    return ctx.max_dev_retries


def resolve_design_track_enabled(state: FactoryState) -> bool:
    """是否执行 UX → UI → 美工（L3 state > Workflow Profile features.design_track）。"""
    ctx = _run_context_or_none(state)
    if ctx is None:
        if "design_track_enabled" in state:
            return bool(state["design_track_enabled"])
        return False
    return resolve_design_track(state, ctx)


# --- 角色节点（占位） ---


@skip_if_disabled("project_manager_draft")
def project_manager_draft(state: FactoryState) -> dict:
    build_run_context_from_state(state)
    req = state.get("human_request", "")
    from auto_studio.backends.runner import invoke_role

    body = invoke_role(
        role_name="project_manager",
        user_prompt=(
            f"人类原始需求：\n{req}\n\n"
            "请按 role.md 产出 `requirement_spec` 正文（Markdown），"
            "须含可检验验收标准 AC-*。"
        ),
        stub_note=f"需求说明草稿 input_len={len(req)}",
    )
    return {"requirement_spec": body}


def pm_clarification_check(state: FactoryState) -> dict:
    """若 requirement_spec 含待澄清项，写入 HITL 并暂停在 hitl_pause。"""
    from datetime import UTC, datetime

    from auto_studio.hitl.pm_clarification import extract_pm_questions

    if state.get("hitl_clarification_resolved"):
        return {}
    spec = state.get("requirement_spec") or ""
    questions = extract_pm_questions(spec)
    if not questions:
        return {"hitl_clarification_resolved": True}
    if state.get("hitl_pending_kind") == "pm_clarification":
        return {}
    return {
        "hitl_pending_kind": "pm_clarification",
        "hitl_questions": questions,
        "hitl_summary": "需求说明中有待澄清项，请答复后工厂继续。",
        "hitl_pending_since": datetime.now(UTC).isoformat(),
    }


def hitl_pause(state: FactoryState) -> dict:
    """图内暂停点：awaiting_human 由 hitl_pending_kind 推断。"""
    return {}


def route_after_pm_clarification(state: FactoryState) -> str:
    if state.get("hitl_pending_kind") == "pm_clarification":
        return "hitl_pause"
    return "tester_testability"


@skip_if_disabled("tester_testability")
def tester_testability(state: FactoryState) -> dict:
    from auto_studio.backends.runner import invoke_role

    spec = state.get("requirement_spec") or ""
    body = invoke_role(
        role_name="tester",
        user_prompt=(
            f"需求说明：\n{spec[:8000]}\n\n"
            "请产出 `testability_review` 正文（Markdown），指出可测试性风险与建议。"
        ),
        stub_note="可测试性评审（关卡前）",
    )
    return {"testability_review": body}


def gate_requirement_confirm(state: FactoryState) -> dict:
    """人工关卡：需求确认。interrupt_before 在本节点前暂停。"""
    return apply_gate_node("gate_requirement_confirm", state)


@skip_if_disabled("ux_designer")
def ux_designer(state: FactoryState) -> dict:
    from auto_studio.backends.runner import invoke_role

    spec = state.get("requirement_spec") or ""
    body = invoke_role(
        role_name="ux_designer",
        user_prompt=f"需求说明：\n{spec[:8000]}\n\n请产出 `ux_spec` 正文。",
        stub_note="体验设计说明（任务流与线框，待 UI）",
    )
    return {"ux_spec": body}


@skip_if_disabled("ui_designer")
def ui_designer(state: FactoryState) -> dict:
    from auto_studio.backends.runner import invoke_role

    ux = state.get("ux_spec") or ""
    body = invoke_role(
        role_name="ui_designer",
        user_prompt=f"UX 说明：\n{ux[:8000]}\n\n请产出 `ui_spec` 正文。",
        stub_note="界面与组件规格（待美工资源）",
    )
    return {"ui_spec": body}


@skip_if_disabled("visual_designer")
def visual_designer(state: FactoryState) -> dict:
    from auto_studio.backends.runner import invoke_role

    ui = state.get("ui_spec") or ""
    body = invoke_role(
        role_name="visual_designer",
        user_prompt=f"UI 规格：\n{ui[:8000]}\n\n请产出 `visual_assets` 清单说明。",
        stub_note="视觉资源清单与文件（待架构/实现）",
    )
    return {"visual_assets": body}


def config_manager_plan(state: FactoryState) -> dict:
    ctx = build_run_context_from_state(state)
    enabled = resolve_design_track_enabled(state)
    track = "enabled" if enabled else "skipped"
    summary = ctx.config_plan_summary()
    return {
        **_touch_artifact(
            state,
            "config_plan",
            "config_manager",
            f"本轮配置管理计划 design_track={track}\n{summary}",
        ),
        "design_track_enabled": enabled,
    }


# 财务三个节点的函数仍保留在本文件，当前图不注册、不连边。
# 需要时把 finance_budget_rough / finance_budget_final / finance_cost_snapshot
# 加回 nodes，并接在 project_manager_scope、gate_architecture_review、project_manager_delivery 之前。


@skip_if_disabled("finance_budget_rough")
def finance_budget_rough(state: FactoryState) -> dict:
    from auto_studio.backends.runner import invoke_role

    spec = state.get("requirement_spec") or ""
    body = invoke_role(
        role_name="finance",
        user_prompt=f"需求说明：\n{spec[:8000]}\n\n请产出 `budget_plan` 粗估正文。",
        stub_note="预算粗估（需求确认前）",
    )
    return {"budget_plan": body, "budget_phase": "rough"}


@skip_if_disabled("project_manager_scope")
def project_manager_scope(state: FactoryState) -> dict:
    existing = (state.get("requirement_spec") or "").rstrip()
    note = _touch_artifact(
        state,
        "requirement_spec",
        "project_manager",
        "需求说明（范围已确认，待架构）",
    )["requirement_spec"]
    body = f"{existing}\n\n---\n\n{note}" if existing else note
    return {"requirement_spec": body}


@skip_if_disabled("architect")
def architect(state: FactoryState) -> dict:
    from auto_studio.backends.runner import invoke_role

    spec = state.get("requirement_spec") or ""
    arch = invoke_role(
        role_name="architect",
        user_prompt=f"需求说明：\n{spec[:8000]}\n\n请产出 `architecture_design` 正文。",
        stub_note="架构设计",
    )
    plan = invoke_role(
        role_name="architect",
        user_prompt=(
            f"架构设计：\n{arch[:6000]}\n\n"
            "请产出 `task_plan` 正文（任务拆分与依赖）。"
        ),
        stub_note="任务计划",
    )
    return {"architecture_design": arch, "task_plan": plan}


@skip_if_disabled("finance_budget_final")
def finance_budget_final(state: FactoryState) -> dict:
    from auto_studio.backends.runner import invoke_role

    arch = state.get("architecture_design") or ""
    body = invoke_role(
        role_name="finance",
        user_prompt=f"架构设计：\n{arch[:8000]}\n\n请产出 `budget_plan` 正式版正文。",
        stub_note="预算正式版（架构评审关卡）",
    )
    return {"budget_plan": body, "budget_phase": "final"}


def gate_architecture_review(state: FactoryState) -> dict:
    """人工关卡：架构评审与预算批准。"""
    return apply_gate_node("gate_architecture_review", state)


@skip_if_disabled("developer")
def developer(state: FactoryState) -> dict:
    from auto_studio.backends.runner import invoke_role

    retries = state.get("dev_retry_count", 0)
    task = state.get("task_plan") or ""
    worktree = state.get("workspace_path") or ""
    request = state.get("human_request") or ""
    scope = ""
    if worktree:
        scope = f"只能修改这个工作树中的文件：{worktree}\n不要修改工作树以外的路径，也不要合并到其他分支。\n"
    body = invoke_role(
        role_name="developer",
        user_prompt=(
            f"{scope}"
            f"人类要求：\n{request[:2000]}\n\n"
            f"任务计划：\n{task[:6000]}\n\n"
            f"请产出本轮 `code_change` 说明（attempt={retries + 1}）。"
        ),
        stub_note=f"代码变更 attempt={retries + 1}",
    )
    return {"code_change": body, "dev_retry_count": retries + 1}


def change_control(state: FactoryState) -> dict:
    from auto_studio.verification.acceptance import classify_change_impact

    impact = classify_change_impact(state.get("change_request") or "")
    note = ""
    if impact:
        note = "变更尚未经过对应关卡批准，不写入新的基线项。"
    return {"change_impact": impact, "change_baseline_note": note}


def route_after_change(state: FactoryState) -> str:
    impact = state.get("change_impact") or ""
    if impact == "scope":
        return "gate_requirement_confirm"
    if impact == "architecture":
        return "gate_architecture_review"
    return "code_reviewer"


@skip_if_disabled("code_reviewer")
def code_reviewer(state: FactoryState) -> dict:
    from auto_studio.backends.runner import invoke_role

    status: ReviewStatus = state.get("review_status") or "pass"
    change = state.get("code_change") or ""
    body = invoke_role(
        role_name="code_reviewer",
        user_prompt=(
            f"代码变更说明：\n{change[:8000]}\n\n"
            f"请产出 `review_report`（当前预设结论 status={status}）。"
        ),
        stub_note=f"评审结论 status={status}",
    )
    return {"review_report": body, "review_status": status}


@skip_if_disabled("tester_execute")
def tester_execute(state: FactoryState) -> dict:
    from auto_studio.backends.runner import invoke_role

    status: TestStatus = state.get("test_status") or "pass"
    spec = state.get("requirement_spec") or ""
    cases = invoke_role(
        role_name="tester",
        user_prompt=f"需求说明：\n{spec[:6000]}\n\n请产出 `test_cases` 正文。",
        stub_note="测试用例",
    )
    report = invoke_role(
        role_name="tester",
        user_prompt=(
            f"测试用例：\n{cases[:6000]}\n\n"
            f"请产出 `test_report`（预设 status={status}）。"
            "若执行了测试命令，须引用命令输出中的 AC-*。"
        ),
        stub_note=f"测试报告 status={status}",
    )
    from auto_studio.verification.command import TestCommandError, run_test_command

    try:
        command = run_test_command(state)
    except TestCommandError as exc:
        return {
            "test_cases": cases,
            "test_report": f"{report}\n\n## 测试命令\n拒绝执行：{exc}",
            "test_status": "fail",
        }
    if command is not None:
        report = f"{report}\n\n{command.transcript}"
        if command.returncode != 0:
            status = "fail"
    return {"test_cases": cases, "test_report": report, "test_status": status}


@skip_if_disabled("qa")
def qa(state: FactoryState) -> dict:
    from auto_studio.backends.runner import invoke_role

    status: QaStatus = state.get("qa_status") or "pass"
    report_in = state.get("test_report") or ""
    body = invoke_role(
        role_name="qa",
        user_prompt=(
            f"测试报告：\n{report_in[:8000]}\n\n"
            f"请产出 `qa_report`（预设 status={status}）。"
            "若需求含 AC-*，须逐条引用测试证据。"
        ),
        stub_note=f"QA 报告 status={status}",
    )
    from auto_studio.verification.acceptance import (
        acceptance_matrix,
        missing_acceptance_ids,
    )

    spec = state.get("requirement_spec") or ""
    evidence = f"{report_in}\n{body}"
    matrix = acceptance_matrix(requirement_spec=spec, evidence=evidence)
    if missing_acceptance_ids(requirement_spec=spec, evidence=evidence):
        status = "fail"
    return {"qa_report": f"{body}\n\n{matrix}", "qa_status": status}


@skip_if_disabled("finance_cost_snapshot")
def finance_cost_snapshot(state: FactoryState) -> dict:
    from auto_studio.backends.runner import invoke_role

    body = invoke_role(
        role_name="finance",
        user_prompt=(
            "请根据本轮产物摘要产出 `cost_report` 成本快照（交付前）。\n"
            f"qa_report 摘要：{(state.get('qa_report') or '')[:4000]}"
        ),
        stub_note="成本快照（交付前）",
    )
    return {"cost_report": body, "budget_phase": "snapshot"}


@skip_if_disabled("project_manager_delivery")
def project_manager_delivery(state: FactoryState) -> dict:
    from auto_studio.backends.runner import invoke_role
    from auto_studio.verification.acceptance import missing_acceptance_ids

    spec = state.get("requirement_spec") or ""
    missing = missing_acceptance_ids(
        requirement_spec=spec,
        evidence=state.get("test_report") or "",
    )
    ready = not missing and state.get("qa_status") != "fail"
    if not ready:
        gap = "、".join(missing) if missing else "QA 未通过"
        return {
            "delivery_report": f"未形成可交付结论：{gap}。无验收证据不视为交付。",
            "delivery_ready": False,
        }
    body = invoke_role(
        role_name="project_manager",
        user_prompt=(
            "请产出 `delivery_report` 交付报告正文（待最终交付关卡）。\n"
            f"测试/QA 摘要：{(state.get('test_report') or '')[:3000]}"
        ),
        stub_note="交付报告（待最终交付关卡）",
    )
    return {"delivery_report": body, "delivery_ready": True}


def gate_final_delivery(state: FactoryState) -> dict:
    """人工关卡：最终交付。"""
    return apply_gate_node("gate_final_delivery", state)


@skip_if_disabled("config_manager_closeout")
def config_manager_closeout(state: FactoryState) -> dict:
    from auto_studio.backends.runner import invoke_role

    baseline = invoke_role(
        role_name="config_manager",
        user_prompt=(
            "请产出 `config_baseline` 交付基线说明。\n"
            f"baseline_log：{(state.get('baseline_log') or '')[:6000]}"
        ),
        stub_note="交付基线",
    )
    retro = invoke_role(
        role_name="config_manager",
        user_prompt="请产出 `config_retro` 模板与配置复盘正文。",
        stub_note="模板与配置复盘",
    )
    return {"config_baseline": baseline, "config_retro": retro}


@skip_if_disabled("process_owner_retro")
def process_owner_retro(state: FactoryState) -> dict:
    from auto_studio.backends.runner import invoke_role

    retro = invoke_role(
        role_name="process_owner",
        user_prompt="请产出 `retro_report`（Top3 问题与改进点）。",
        stub_note="本轮复盘 Top3",
    )
    proposals = invoke_role(
        role_name="process_owner",
        user_prompt="请产出 `process_proposals` 流程与角色改进提案。",
        stub_note="流程与角色改进提案",
    )
    from auto_studio.backends.cost import take_cost_lines
    from auto_studio.verification.retro import scorecard

    audit = str(state.get("hitl_audit_log") or state.get("run_record") or "").strip()
    run_record = audit or "[engine] 本轮无 HITL 审计条目"
    costs = "\n".join(take_cost_lines())
    card = scorecard(state)
    proposal_id = ""
    worktree = str(state.get("workspace_path") or "")
    if worktree:
        from auto_studio.evolution.proposals import save_retro_proposal

        proposal_id = save_retro_proposal(worktree, proposals)
    pending = "提案状态：pending。未经批准不得修改角色定义或流程。"
    if proposal_id:
        pending = f"{pending}\n提案编号：{proposal_id}"
    return {
        "retro_report": f"{retro}\n\n{card}",
        "process_proposals": proposals + "\n\n" + pending,
        "run_record": run_record,
        "cost_ledger": costs,
    }


def escalate_dev_retry(state: FactoryState) -> dict:
    from datetime import UTC, datetime

    summary = "开发回退次数已达上限，请选择：继续 / 暂停 / 终止。"
    return {
        "change_request": summary,
        "hitl_pending_kind": "escalation",
        "hitl_summary": summary,
        "hitl_questions": [],
        "hitl_pending_since": datetime.now(UTC).isoformat(),
    }


# --- 条件路由 ---


def route_after_review(state: FactoryState) -> str:
    if state.get("review_status") == "fail":
        if state.get("dev_retry_count", 0) >= max_dev_retries_for_state(state):
            return "escalate_dev_retry"
        return "developer"
    return "tester_execute"


def route_after_test(state: FactoryState) -> str:
    if state.get("test_status") == "fail":
        if state.get("dev_retry_count", 0) >= max_dev_retries_for_state(state):
            return "escalate_dev_retry"
        return "developer"
    return "qa"


def route_after_qa(state: FactoryState) -> str:
    if state.get("qa_status") == "fail":
        if state.get("dev_retry_count", 0) >= max_dev_retries_for_state(state):
            return "escalate_dev_retry"
        return "developer"
    return "project_manager_delivery"


def route_after_config_plan(state: FactoryState) -> str:
    if state.get("design_track_enabled"):
        return "ux_designer"
    return "project_manager_scope"


def _route_after_gate_rejected(state: FactoryState, on_approved: str) -> str:
    if state.get("last_gate_decision") == "rejected":
        return "__end__"
    return on_approved


def route_after_requirement_gate(state: FactoryState) -> str:
    return _route_after_gate_rejected(state, "config_manager_plan")


def route_after_architecture_gate(state: FactoryState) -> str:
    return _route_after_gate_rejected(state, "developer")


def route_after_final_delivery_gate(state: FactoryState) -> str:
    return _route_after_gate_rejected(state, "config_manager_closeout")


def route_after_delivery(state: FactoryState) -> str:
    if state.get("delivery_ready") is False:
        return "escalate_dev_retry"
    return "gate_final_delivery"


def _with_stop_guard(fn):
    """停止请求到达后，不再执行后续节点。"""

    def wrapped(state: FactoryState) -> dict:
        from auto_studio.hitl.control import (
            RunPaused,
            RunStopped,
            is_pause_requested,
            is_stop_requested,
        )

        if is_stop_requested():
            raise RunStopped("本轮已停止")
        if is_pause_requested():
            raise RunPaused("本轮已暂停")
        result = fn(state)
        if is_stop_requested():
            raise RunStopped("本轮已停止")
        if is_pause_requested():
            raise RunPaused("本轮已暂停")
        return result

    wrapped.__name__ = getattr(fn, "__name__", "node")
    wrapped.__doc__ = getattr(fn, "__doc__", None)
    return wrapped


def build_graph() -> StateGraph:
    builder = StateGraph(FactoryState)

    nodes = {
        "project_manager_draft": project_manager_draft,
        "tester_testability": tester_testability,
        "gate_requirement_confirm": gate_requirement_confirm,
        "ux_designer": ux_designer,
        "ui_designer": ui_designer,
        "visual_designer": visual_designer,
        "config_manager_plan": config_manager_plan,
        "project_manager_scope": project_manager_scope,
        "architect": architect,
        "gate_architecture_review": gate_architecture_review,
        "developer": developer,
        "code_reviewer": code_reviewer,
        "tester_execute": tester_execute,
        "qa": qa,
        "project_manager_delivery": project_manager_delivery,
        "gate_final_delivery": gate_final_delivery,
        "config_manager_closeout": config_manager_closeout,
        "process_owner_retro": process_owner_retro,
        "escalate_dev_retry": escalate_dev_retry,
        "pm_clarification_check": pm_clarification_check,
        "hitl_pause": hitl_pause,
        "change_control": change_control,
    }
    for name, fn in nodes.items():
        builder.add_node(name, _with_stop_guard(fn))

    builder.add_edge(START, "project_manager_draft")
    builder.add_edge("project_manager_draft", "pm_clarification_check")
    builder.add_conditional_edges(
        "pm_clarification_check",
        route_after_pm_clarification,
        {"hitl_pause": "hitl_pause", "tester_testability": "tester_testability"},
    )
    builder.add_edge("hitl_pause", END)
    builder.add_edge("tester_testability", "gate_requirement_confirm")
    builder.add_conditional_edges(
        "gate_requirement_confirm",
        route_after_requirement_gate,
        {"config_manager_plan": "config_manager_plan", "__end__": END},
    )
    builder.add_conditional_edges(
        "config_manager_plan",
        route_after_config_plan,
        {
            "ux_designer": "ux_designer",
            "project_manager_scope": "project_manager_scope",
        },
    )
    builder.add_edge("ux_designer", "ui_designer")
    builder.add_edge("ui_designer", "visual_designer")
    builder.add_edge("visual_designer", "project_manager_scope")
    builder.add_edge("project_manager_scope", "architect")
    builder.add_edge("architect", "gate_architecture_review")
    builder.add_conditional_edges(
        "gate_architecture_review",
        route_after_architecture_gate,
        {"developer": "developer", "__end__": END},
    )
    builder.add_edge("developer", "change_control")
    builder.add_conditional_edges(
        "change_control",
        route_after_change,
        {
            "code_reviewer": "code_reviewer",
            "gate_requirement_confirm": "gate_requirement_confirm",
            "gate_architecture_review": "gate_architecture_review",
        },
    )
    builder.add_conditional_edges("code_reviewer", route_after_review)
    builder.add_conditional_edges("tester_execute", route_after_test)
    builder.add_conditional_edges("qa", route_after_qa)
    builder.add_conditional_edges(
        "project_manager_delivery",
        route_after_delivery,
        {
            "gate_final_delivery": "gate_final_delivery",
            "escalate_dev_retry": "escalate_dev_retry",
        },
    )
    builder.add_conditional_edges(
        "gate_final_delivery",
        route_after_final_delivery_gate,
        {"config_manager_closeout": "config_manager_closeout", "__end__": END},
    )
    builder.add_edge("config_manager_closeout", "process_owner_retro")
    builder.add_edge("process_owner_retro", END)
    builder.add_edge("escalate_dev_retry", END)

    return builder


# 财务节点暂不注册进图。保留函数引用，避免以后接回时从本文件丢失。
_FINANCE_NODES_RESERVED = {
    "finance_budget_rough": finance_budget_rough,
    "finance_budget_final": finance_budget_final,
    "finance_cost_snapshot": finance_cost_snapshot,
}


# 须同时提供 checkpointer，interrupt_before 才会在 run 边界生效；
# VizLang 若发现已有 checkpointer 会整图复用，不会丢掉 interrupt 配置。
INTERRUPT_BEFORE_GATES = [
    "gate_requirement_confirm",
    "gate_architecture_review",
    "gate_final_delivery",
]


def compile_graph(checkpointer=None):
    saver = checkpointer if checkpointer is not None else default_checkpointer()
    return build_graph().compile(
        checkpointer=saver,
        interrupt_before=INTERRUPT_BEFORE_GATES,
    )


graph = compile_graph()
