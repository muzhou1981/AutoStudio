"""GeniStudio 默认工作流程：图状态、内置节点实现与编译入口。

节点顺序、可选分支与路由写在 workflows/factory_default/workflow.yaml，
由 workflows/executable.py 编译。本文件提供不调用 Agent 的系统节点（handler）
与活动的内置后处理（effect）；调用 Agent 的步骤都按通用活动执行。
"""

from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, Literal, NamedTuple, TypedDict

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
    # 这一轮各活动节点选用的 Skill。键是节点标识；MCP 是全局配置，不在这里。
    node_tools: dict[str, dict[str, list[str]]]
    # 这一轮各角色选用的模型。空着的角色沿用配置里的默认模型。
    role_models: dict[str, str]
    # 本轮角色推理覆盖；缺省继承项目/工厂，default 表示 Codex 默认。
    role_reasoning_efforts: dict[str, str]
    # 本轮角色 Fast 模式：on 或 off；缺省交给模型默认。
    role_fast_modes: dict[str, str]
    # 本轮角色的其它模型参数（如上下文长度）：参数名到取值；缺省交给模型默认。
    role_model_params: dict[str, dict[str, str]]
    return_target: str
    escalated_from: str
    # 判定类活动未通过时写入，供被退回的活动修复；该活动执行后清空。
    return_feedback: str


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


# --- 系统节点：不调用 Agent ---


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


def change_control(state: FactoryState) -> dict:
    from geni_studio.verification.acceptance import classify_change_impact

    request = state.get("change_request") or ""
    impact = classify_change_impact(request)
    if not impact:
        return {"change_impact": "", "change_baseline_note": ""}
    note = f"变更尚未经过对应关卡批准，不写入新的基线项。\n变更请求：\n{request}"
    # 变更请求交给关卡后即消费，避免关卡批准后再次被路由回关卡。
    return {"change_impact": impact, "change_baseline_note": note, "change_request": ""}


# --- 活动的内置后处理 ---
# 活动的提示词由 workflows/executable.py 按通用活动拼装（输入产物、返工反馈、所选 Skill）。
# 流程文件以 effect 引用下面的条目，在 Agent 返回后做判定并写入流程状态。


class Effect(NamedTuple):
    # 拆分产物后的更新 -> 最终更新
    finish: Callable[[FactoryState, dict], dict]
    # 追加到提示词的段落
    prompt: Callable[[FactoryState], list[str]] | None = None
    # 返回更新时不调用 Agent
    precheck: Callable[[FactoryState], dict | None] | None = None
    # 提示词要求附上结论块
    verdict: bool = False


def _developer_prompt(state: FactoryState) -> list[str]:
    attempt = int(state.get("dev_retry_count") or 0) + 1
    parts: list[str] = []
    worktree = state.get("workspace_path") or ""
    if worktree:
        parts.append(f"只能修改这个工作树中的文件：{worktree}\n不要修改工作树以外的路径，也不要合并到其他分支。")
    parts.append(f"这是本轮第 {attempt} 次开发（attempt={attempt}）。")
    return parts


def _developer_finish(state: FactoryState, update: dict) -> dict:
    from geni_studio.verification.verdict import parse_change_request

    update.pop("change_request", None)
    impact, raw = parse_change_request(str(update.get("code_change") or ""))
    if raw:
        update["change_request"] = f"IMPACT: {impact}\n{raw}" if impact else raw
    update["dev_retry_count"] = int(state.get("dev_retry_count") or 0) + 1
    update["return_feedback"] = ""
    return update


def _review_finish(state: FactoryState, update: dict) -> dict:
    from geni_studio.backends.runner import role_is_simulated
    from geni_studio.verification.verdict import judge, with_verdict

    preset: ReviewStatus = state.get("review_status") or "pass"
    body = str(update.get("review_report") or "")
    verdict = judge(body, simulated=role_is_simulated("code_reviewer"), preset=preset)
    report = with_verdict(body, verdict)
    update.update({"review_report": report, "review_status": verdict.status})
    if not verdict.passed:
        update["return_feedback"] = f"代码评审未通过：\n{report}"
    return update


def _test_finish(state: FactoryState, update: dict) -> dict:
    from geni_studio.backends.runner import role_is_simulated
    from geni_studio.verification.command import verified_report
    from geni_studio.verification.verdict import Verdict, judge, with_verdict

    preset: TestStatus = state.get("test_status") or "pass"
    report = str(update.get("test_report") or "")
    claimed = judge(report, simulated=role_is_simulated("tester"), preset=preset)
    report, status = verified_report(
        state, report, claimed.status, claim_binding=claimed.source in {"block", "legacy", "invalid"}
    )
    error = ""
    if status == "fail":
        error = claimed.error or "验证命令未通过或缺少机器验证证据。"
    final = Verdict(status, ac=claimed.ac, summary=claimed.summary, source=claimed.source, error=error)  # type: ignore[arg-type]
    report = with_verdict(report, final)
    update.update({"test_report": report, "test_status": status})
    if status == "fail":
        update["return_feedback"] = f"测试未通过：\n{report}"
    return update


def _qa_finish(state: FactoryState, update: dict) -> dict:
    from geni_studio.backends.runner import role_is_simulated
    from geni_studio.verification.acceptance import (
        acceptance_matrix,
        acceptance_sources,
    )
    from geni_studio.verification.verdict import Verdict, judge, with_verdict

    preset: QaStatus = state.get("qa_status") or "pass"
    body = str(update.get("qa_report") or "")
    report_in = state.get("test_report") or ""
    simulated = role_is_simulated("qa")
    verdict = judge(body, simulated=simulated, preset=preset)
    sources = acceptance_sources(
        requirement_spec=state.get("requirement_spec") or "",
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
    update.update({"qa_report": report, "qa_status": status})
    if status == "fail":
        update["return_feedback"] = f"QA 未通过：\n{report}"
    return update


def _delivery_precheck(state: FactoryState) -> dict | None:
    from geni_studio.backends.runner import role_is_simulated
    from geni_studio.verification.acceptance import acceptance_sources
    from geni_studio.verification.verdict import parse_verdict

    test_report = state.get("test_report") or ""
    qa_report = state.get("qa_report") or ""
    sources = acceptance_sources(
        requirement_spec=state.get("requirement_spec") or "",
        verdicts=[parse_verdict(qa_report)],
        test_report=test_report,
        simulated_evidence=f"{test_report}\n{qa_report}" if role_is_simulated("qa") else None,
    )
    missing = [ac for ac, source in sources.items() if not source]
    if not missing and state.get("qa_status") != "fail":
        return None
    gap = "、".join(missing) if missing else "QA 未通过"
    return {
        "delivery_report": f"未形成可交付结论：{gap}。无验收证据不视为交付。",
        "delivery_ready": False,
    }


def _delivery_finish(state: FactoryState, update: dict) -> dict:
    update["delivery_ready"] = True
    return update


def _retro_finish(state: FactoryState, update: dict) -> dict:
    from geni_studio.backends.cost import take_cost_lines
    from geni_studio.verification.retro import scorecard

    proposals = str(update.get("process_proposals") or "")
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
    update.update(
        {
            "retro_report": card,
            "process_proposals": proposals + "\n\n" + pending,
            "run_record": run_record,
            "cost_ledger": costs,
        }
    )
    return update


def _budget_phase(phase: str) -> Callable[[FactoryState, dict], dict]:
    def finish(state: FactoryState, update: dict) -> dict:
        update["budget_phase"] = phase
        return update

    return finish


EFFECTS: dict[str, Effect] = {
    "developer": Effect(_developer_finish, prompt=_developer_prompt),
    "code_review": Effect(_review_finish, verdict=True),
    "test_execute": Effect(_test_finish, verdict=True),
    "qa_gate": Effect(_qa_finish, verdict=True),
    "delivery": Effect(_delivery_finish, precheck=_delivery_precheck),
    "retro": Effect(_retro_finish),
    "budget_rough": Effect(_budget_phase("rough")),
    "budget_final": Effect(_budget_phase("final")),
    "cost_snapshot": Effect(_budget_phase("snapshot")),
}


def run_builtin_node(node_id: str, state: FactoryState) -> dict:
    """按内置流程中的定义单独执行一个节点，供调试与测试使用。"""
    from geni_studio.workflows.executable import step_callable

    for node in builtin_definition()["nodes"]:
        if node.get("id") == node_id:
            return step_callable(node, builtin=True)(state)
    raise KeyError(node_id)


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
