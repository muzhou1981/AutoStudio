"""GeniStudio 默认工作流程：图状态、内置节点实现与编译入口。

节点顺序、可选分支与路由写在 workflows/factory_default/workflow.yaml，
由 workflows/executable.py 编译；本文件中的节点函数以系统节点 handler 的名义被引用。
"""

from pathlib import Path
from typing import Annotated, Any, Literal, TypedDict

from geni_studio.config.context import (
    ConfigError,
    build_run_context_from_state,
    resolve_design_track,
)
from geni_studio.workflows.node_wrap import skip_if_disabled
from geni_studio.workspace.checkpoint import default_checkpointer

# 无有效 project/scenario 配置时的回退上限
DEFAULT_MAX_DEV_RETRIES = 3

ReviewStatus = Literal["pass", "fail"]
TestStatus = Literal["pass", "fail"]
QaStatus = Literal["pass", "fail"]
GateDecision = Literal["approved", "rejected"]


def _merge_maps(left: dict | None, right: dict | None) -> dict:
    """并行支路各自写入不同的键，合并时互不覆盖。"""
    merged = dict(left or {})
    merged.update(right or {})
    return merged


class FactoryState(TypedDict, total=False):
    """与 roles/*/role.md 中产物名对齐；值为占位字符串，接入 Agent 后改为结构化产物。"""

    # 引擎 / 人类输入
    human_request: str
    attachments: list[str]
    scenario_key: str
    project_id: str
    run_name: str
    config_snapshot_scenario: str
    config_snapshot_project: str
    config_snapshot_effective: dict[str, Any]
    workflow_definition: dict[str, Any]
    workflow_definition_ref: str
    design_track_enabled: bool
    finance_enabled: bool
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
    compliance_report: str

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
    awaiting_since: str
    gate_timeout_recorded: bool
    gate_timeout_note: str
    hitl_audit_log: str
    escalation_choice: str
    hitl_clarification_resolved: bool
    workspace_path: str
    # 自我改进开工时目标仓库检出的分支。其他流程为空。
    base_branch: str
    # 程序员在当前分支提交入库后的记录。
    land_record: str
    test_command: str
    change_impact: str
    change_baseline_note: str
    delivery_ready: bool
    run_stopped: bool
    stopped_at: str
    run_paused: bool
    paused_at: str
    run_interrupted: bool
    interrupted_at: str

    # 项目所选流程编译出的当轮图（ADR 0005）。未选流程时这些字段为空。
    workflow_id: str
    workflow_gates: list[str]
    workflow_nodes: list[dict[str, Any]]
    return_counts: Annotated[dict[str, int], _merge_maps]
    return_decisions: Annotated[dict[str, str], _merge_maps]
    branch_artifacts: Annotated[dict[str, str], _merge_maps]
    # 流程自定义、图状态里没有字段的产物（ADR 0013）。
    extra_artifacts: Annotated[dict[str, str], _merge_maps]
    # 产物登记：产出节点、第几次产出、sha256、落盘路径（ADR 0013）。
    artifact_meta: Annotated[dict[str, dict], _merge_maps]
    # 并行支路的快照工作树（"<并行>:<支路>"）与快照提交（"<并行>:__base__"）。
    branch_workspaces: Annotated[dict[str, str], _merge_maps]
    # 这一轮各活动节点选用的 Skill 与 MCP。键是节点标识。
    node_tools: dict[str, dict[str, list[str]]]
    # 这一轮各角色选用的模型。空着的角色沿用配置里的默认模型。
    role_models: dict[str, str]
    # 本轮角色推理覆盖；缺省继承项目/工厂，default 表示 Codex 默认。
    role_reasoning_efforts: dict[str, str]
    return_target: str
    escalated_from: str
    # 判定类活动未通过时写入，供被退回的活动修复；该活动执行后清空。
    return_feedback: str


def _touch_artifact(state: FactoryState, key: str, role: str, note: str) -> dict:
    return {key: f"[stub:{role}] {note}"}


def _ref(state: FactoryState, key: str, label: str, role: str, value: str | None = None) -> str:
    """上游产物在提示词中的写法；不截断。"""
    from geni_studio.workflows.artifacts import reference

    text = reference(state, key, label, role=role, value=value)
    return f"{text}\n\n" if text else ""


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
    from geni_studio.backends.runner import invoke_role
    from geni_studio.hitl.attachments import prompt_section

    attached = prompt_section(state.get("attachments"))
    body = invoke_role(
        role_name="project_manager",
        user_prompt=(
            f"人类原始需求：\n{req}\n\n"
            + (f"{attached}\n\n" if attached else "")
            + "请按 role.md 产出 `requirement_spec` 正文（Markdown），"
            "须含可检验验收标准 AC-*。"
        ),
        stub_note=f"需求说明草稿 input_len={len(req)}",
    )
    return {"requirement_spec": body}


def pm_clarification_check(state: FactoryState) -> dict:
    """若 requirement_spec 含待澄清项，写入 HITL 并暂停在 hitl_pause。"""
    from datetime import UTC, datetime

    from geni_studio.hitl.pm_clarification import extract_pm_questions

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


@skip_if_disabled("tester_testability")
def tester_testability(state: FactoryState) -> dict:
    from geni_studio.backends.runner import invoke_role

    body = invoke_role(
        role_name="tester",
        user_prompt=(
            _ref(state, "requirement_spec", "需求说明", "tester")
            + "请产出 `testability_review` 正文（Markdown），指出可测试性风险与建议。"
        ),
        stub_note="可测试性评审（关卡前）",
    )
    return {"testability_review": body}


@skip_if_disabled("ux_designer")
def ux_designer(state: FactoryState) -> dict:
    from geni_studio.backends.runner import invoke_role

    body = invoke_role(
        role_name="ux_designer",
        user_prompt=_ref(state, "requirement_spec", "需求说明", "ux_designer") + "请产出 `ux_spec` 正文。",
        stub_note="体验设计说明（任务流与线框，待 UI）",
    )
    return {"ux_spec": body}


@skip_if_disabled("ui_designer")
def ui_designer(state: FactoryState) -> dict:
    from geni_studio.backends.runner import invoke_role

    body = invoke_role(
        role_name="ui_designer",
        user_prompt=_ref(state, "ux_spec", "UX 说明", "ui_designer") + "请产出 `ui_spec` 正文。",
        stub_note="界面与组件规格（待美工资源）",
    )
    return {"ui_spec": body}


@skip_if_disabled("visual_designer")
def visual_designer(state: FactoryState) -> dict:
    from geni_studio.backends.runner import invoke_role

    body = invoke_role(
        role_name="visual_designer",
        user_prompt=_ref(state, "ui_spec", "UI 规格", "visual_designer") + "请产出 `visual_assets` 清单说明。",
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


@skip_if_disabled("finance_budget_rough")
def finance_budget_rough(state: FactoryState) -> dict:
    from geni_studio.backends.runner import invoke_role

    body = invoke_role(
        role_name="finance",
        user_prompt=_ref(state, "requirement_spec", "需求说明", "finance") + "请产出 `budget_plan` 粗估正文。",
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
    from geni_studio.backends.runner import invoke_role

    arch = invoke_role(
        role_name="architect",
        user_prompt=_ref(state, "requirement_spec", "需求说明", "architect") + "请产出 `architecture_design` 正文。",
        stub_note="架构设计",
    )
    plan = invoke_role(
        role_name="architect",
        user_prompt=(
            _ref(state, "architecture_design", "架构设计", "architect", value=arch)
            + "请产出 `task_plan` 正文（任务拆分与依赖）。"
        ),
        stub_note="任务计划",
    )
    return {"architecture_design": arch, "task_plan": plan}


@skip_if_disabled("finance_budget_final")
def finance_budget_final(state: FactoryState) -> dict:
    from geni_studio.backends.runner import invoke_role

    body = invoke_role(
        role_name="finance",
        user_prompt=_ref(state, "architecture_design", "架构设计", "finance") + "请产出 `budget_plan` 正式版正文。",
        stub_note="预算正式版（架构评审关卡）",
    )
    return {"budget_plan": body, "budget_phase": "final"}


@skip_if_disabled("developer")
def developer(state: FactoryState) -> dict:
    from geni_studio.backends.runner import invoke_role
    from geni_studio.hitl.attachments import prompt_section

    retries = state.get("dev_retry_count", 0)
    task = state.get("task_plan") or ""
    worktree = state.get("workspace_path") or ""
    request = state.get("human_request") or ""
    scope = ""
    if worktree:
        scope = f"只能修改这个工作树中的文件：{worktree}\n不要修改工作树以外的路径，也不要合并到其他分支。\n"
    from geni_studio.verification.verdict import (
        CHANGE_REQUEST_INSTRUCTION,
        parse_change_request,
    )

    attached = prompt_section(state.get("attachments"))
    feedback = state.get("return_feedback") or ""
    body = invoke_role(
        role_name="developer",
        user_prompt=(
            f"{scope}"
            f"人类要求：\n{request}\n\n"
            + (f"{attached}\n\n" if attached else "")
            + _ref(state, "architecture_design", "架构设计", "developer")
            + (_ref(state, "task_plan", "任务计划", "developer") or f"任务计划：\n{task}\n\n")
            + (f"## 需要修复的问题\n上一轮未通过，原因如下，请逐条修复：\n{feedback}\n\n" if feedback else "")
            + f"{CHANGE_REQUEST_INSTRUCTION}\n\n"
            f"请产出本轮 `code_change` 说明（attempt={retries + 1}）。"
        ),
        stub_note=f"代码变更 attempt={retries + 1}",
    )
    update: dict = {"code_change": body, "dev_retry_count": retries + 1, "return_feedback": ""}
    impact, raw = parse_change_request(body)
    if raw:
        update["change_request"] = f"IMPACT: {impact}\n{raw}" if impact else raw
    return update


def change_control(state: FactoryState) -> dict:
    from geni_studio.verification.acceptance import classify_change_impact

    request = state.get("change_request") or ""
    impact = classify_change_impact(request)
    if not impact:
        return {"change_impact": "", "change_baseline_note": ""}
    note = f"变更尚未经过对应关卡批准，不写入新的基线项。\n变更请求：\n{request}"
    # 变更请求交给关卡后即消费，避免关卡批准后再次被路由回关卡。
    return {"change_impact": impact, "change_baseline_note": note, "change_request": ""}


@skip_if_disabled("code_reviewer")
def code_reviewer(state: FactoryState) -> dict:
    from geni_studio.backends.runner import invoke_role, role_is_simulated
    from geni_studio.verification.verdict import (
        VERDICT_INSTRUCTION,
        judge,
        with_verdict,
    )

    preset: ReviewStatus = state.get("review_status") or "pass"
    change = state.get("code_change") or ""
    body = invoke_role(
        role_name="code_reviewer",
        user_prompt=(
            _ref(state, "architecture_design", "架构设计", "code_reviewer")
            + _ref(state, "task_plan", "任务计划", "code_reviewer")
            + (_ref(state, "code_change", "代码变更说明", "code_reviewer") or f"代码变更说明：\n{change}\n\n")
            + "请产出 `review_report`。\n\n"
            f"{VERDICT_INSTRUCTION}"
        ),
        stub_note=f"评审结论 status={preset}",
    )
    verdict = judge(body, simulated=role_is_simulated("code_reviewer"), preset=preset)
    report = with_verdict(body, verdict)
    update = {"review_report": report, "review_status": verdict.status}
    if not verdict.passed:
        update["return_feedback"] = f"代码评审未通过：\n{report}"
    return update


@skip_if_disabled("tester_execute")
def tester_execute(state: FactoryState) -> dict:
    from geni_studio.backends.runner import invoke_role, role_is_simulated
    from geni_studio.verification.command import verified_report
    from geni_studio.verification.verdict import (
        VERDICT_INSTRUCTION,
        Verdict,
        judge,
        with_verdict,
    )

    preset: TestStatus = state.get("test_status") or "pass"
    cases = invoke_role(
        role_name="tester",
        user_prompt=_ref(state, "requirement_spec", "需求说明", "tester") + "请产出 `test_cases` 正文。",
        stub_note="测试用例",
    )
    report = invoke_role(
        role_name="tester",
        user_prompt=(
            _ref(state, "test_cases", "测试用例", "tester", value=cases)
            + _ref(state, "code_change", "代码变更说明", "tester")
            + "请产出 `test_report`。若执行了测试命令，须引用命令输出中的 AC-*。\n\n"
            f"{VERDICT_INSTRUCTION}"
        ),
        stub_note=f"测试报告 status={preset}",
    )
    claimed = judge(report, simulated=role_is_simulated("tester"), preset=preset)
    report, status = verified_report(
        state, report, claimed.status, claim_binding=claimed.source in {"block", "legacy", "invalid"}
    )
    error = ""
    if status == "fail":
        error = claimed.error or "验证命令未通过或缺少机器验证证据。"
    final = Verdict(status, ac=claimed.ac, summary=claimed.summary, source=claimed.source, error=error)  # type: ignore[arg-type]
    report = with_verdict(report, final)
    update = {"test_cases": cases, "test_report": report, "test_status": status}
    if status == "fail":
        update["return_feedback"] = f"测试未通过：\n{report}"
    return update


@skip_if_disabled("qa")
def qa(state: FactoryState) -> dict:
    from geni_studio.backends.runner import invoke_role, role_is_simulated
    from geni_studio.verification.acceptance import (
        acceptance_matrix,
        acceptance_sources,
    )
    from geni_studio.verification.verdict import (
        VERDICT_INSTRUCTION,
        Verdict,
        judge,
        with_verdict,
    )

    preset: QaStatus = state.get("qa_status") or "pass"
    spec = state.get("requirement_spec") or ""
    report_in = state.get("test_report") or ""
    body = invoke_role(
        role_name="qa",
        user_prompt=(
            (_ref(state, "requirement_spec", "需求说明", "qa") or "需求说明：\n\n\n")
            + (_ref(state, "test_report", "测试报告", "qa") or "测试报告：\n\n\n")
            + "请产出 `qa_report`。若需求含 AC-*，须逐条引用测试证据，"
            "并在结论块的 ac 中逐条给出 pass / fail / untested。\n\n"
            f"{VERDICT_INSTRUCTION}"
        ),
        stub_note=f"QA 报告 status={preset}",
    )
    simulated = role_is_simulated("qa")
    verdict = judge(body, simulated=simulated, preset=preset)
    sources = acceptance_sources(
        requirement_spec=spec,
        verdicts=[verdict],
        test_report=report_in,
        simulated_evidence=f"{report_in}\n{body}" if simulated else None,
    )
    missing = [ac for ac, source in sources.items() if not source]
    status: QaStatus = verdict.status
    error = verdict.error
    if missing:
        status, error = "fail", error or f"验收标准缺少证据：{'、'.join(missing)}"
    if state.get("test_status") == "fail":
        status, error = "fail", error or "测试未通过。"
    final = Verdict(status, ac=verdict.ac, summary=verdict.summary, source=verdict.source, error=error)
    report = with_verdict(f"{body}\n\n{acceptance_matrix(sources)}", final)
    update = {"qa_report": report, "qa_status": status}
    if status == "fail":
        update["return_feedback"] = f"QA 未通过：\n{report}"
    return update


@skip_if_disabled("finance_cost_snapshot")
def finance_cost_snapshot(state: FactoryState) -> dict:
    from geni_studio.backends.runner import invoke_role

    body = invoke_role(
        role_name="finance",
        user_prompt=(
            "请根据本轮产物产出 `cost_report` 成本快照（交付前）。\n\n"
            + _ref(state, "qa_report", "qa_report", "finance")
        ),
        stub_note="成本快照（交付前）",
    )
    return {"cost_report": body, "budget_phase": "snapshot"}


@skip_if_disabled("project_manager_delivery")
def project_manager_delivery(state: FactoryState) -> dict:
    from geni_studio.backends.runner import invoke_role, role_is_simulated
    from geni_studio.verification.acceptance import acceptance_sources
    from geni_studio.verification.verdict import parse_verdict

    spec = state.get("requirement_spec") or ""
    test_report = state.get("test_report") or ""
    qa_report = state.get("qa_report") or ""
    sources = acceptance_sources(
        requirement_spec=spec,
        verdicts=[parse_verdict(qa_report)],
        test_report=test_report,
        simulated_evidence=f"{test_report}\n{qa_report}" if role_is_simulated("qa") else None,
    )
    missing = [ac for ac, source in sources.items() if not source]
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
            "请产出 `delivery_report` 交付报告正文（待最终交付关卡）。\n\n"
            + _ref(state, "test_report", "测试报告", "project_manager")
            + _ref(state, "qa_report", "QA 报告", "project_manager")
        ),
        stub_note="交付报告（待最终交付关卡）",
    )
    return {"delivery_report": body, "delivery_ready": True}


@skip_if_disabled("config_manager_closeout")
def config_manager_closeout(state: FactoryState) -> dict:
    from geni_studio.backends.runner import invoke_role

    baseline = invoke_role(
        role_name="config_manager",
        user_prompt=(
            "请产出 `config_baseline` 交付基线说明。\n"
            f"baseline_log：{state.get('baseline_log') or ''}"
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
    from geni_studio.backends.runner import invoke_role

    proposals = invoke_role(
        role_name="process_owner",
        user_prompt="请产出 `process_proposals` 流程与角色改进提案。",
        stub_note="流程与角色改进提案",
    )
    from geni_studio.backends.cost import take_cost_lines
    from geni_studio.verification.retro import scorecard

    audit = str(state.get("hitl_audit_log") or state.get("run_record") or "").strip()
    run_record = audit or "[engine] 本轮无 HITL 审计条目"
    prior_costs = str(state.get("cost_ledger") or "").strip()
    fresh = [line for line in take_cost_lines() if line not in prior_costs]
    costs = "\n".join(part for part in (prior_costs, "\n".join(fresh)) if part).strip()
    card = scorecard({**state, "cost_ledger": costs})
    proposal_id = ""
    worktree = str(state.get("workspace_path") or "")
    if worktree:
        from geni_studio.evolution.proposals import save_retro_proposal

        proposal_id = save_retro_proposal(worktree, proposals)
    pending = "提案状态：pending。未经批准不得修改角色定义或流程。"
    if proposal_id:
        pending = f"{pending}\n提案编号：{proposal_id}"
    return {
        "retro_report": card,
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


def _finance_enabled(state: FactoryState) -> bool:
    if "finance_enabled" in state:
        return bool(state.get("finance_enabled"))
    ctx = _run_context_or_none(state)
    if ctx is None:
        return False
    return ctx.feature_finance()


def _with_stop_guard(fn):
    """停止请求到达后，不再执行后续节点。"""

    def wrapped(state: FactoryState) -> dict:
        from geni_studio.hitl.control import (
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
        # 已完成节点必须提交状态；暂停由下一个节点进入前处理。
        return result

    wrapped.__name__ = getattr(fn, "__name__", "node")
    wrapped.__doc__ = getattr(fn, "__doc__", None)
    return wrapped


_BUILTIN_ROOT = Path(__file__).resolve().parents[3]
_builtin: dict | None = None


def builtin_definition() -> dict:
    """内置流程 workflows/factory_default/workflow.yaml 编译前的展开定义；节点与路由都在该文件中声明。"""
    global _builtin
    if _builtin is None:
        from geni_studio.config.workflow_defs import get_workflow
        from geni_studio.workflows.executable import _prepare_flat, resolve_executable

        loaded = get_workflow("factory_default", root=_BUILTIN_ROOT)["workflow"]
        _builtin = _prepare_flat(resolve_executable(loaded, root=_BUILTIN_ROOT), _BUILTIN_ROOT)
    return _builtin


# 须同时提供 checkpointer，interrupt_before 才会在 run 边界生效；
# VizLang 若发现已有 checkpointer 会整图复用，不会丢掉 interrupt 配置。
def compile_graph(checkpointer=None):
    from geni_studio.workflows.executable import compile_workflow

    saver = checkpointer if checkpointer is not None else default_checkpointer()
    return compile_workflow(builtin_definition(), checkpointer=saver)


_graph = None


def get_graph():
    """进程级默认图；首次访问时编译，避免导入即打开检查点库。"""
    global _graph
    if _graph is None:
        _graph = compile_graph()
    return _graph


def __getattr__(name: str):
    if name == "graph":
        return get_graph()
    raise AttributeError(name)
