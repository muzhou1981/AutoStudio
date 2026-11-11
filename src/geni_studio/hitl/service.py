"""LangGraph Run 与 HITL 提交（Web / 飞书共用）。"""

from __future__ import annotations

import threading
import uuid
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from langgraph.graph.state import CompiledStateGraph

from geni_studio.backends.cost import (
    begin_cost_log,
    end_cost_log,
    reset_project_id,
    set_project_id,
    take_cost_lines,
)
from geni_studio.config.context import ConfigError, build_run_context_from_state
from geni_studio.hitl.choices import choice_groups_from_reading, choices_from_reading
from geni_studio.hitl.constants import GATE_NODES, gate_summary
from geni_studio.hitl.hitl_audit import audit_patch
from geni_studio.hitl.pm_clarification import merge_clarification_reply
from geni_studio.hitl.rail import build_rail
from geni_studio.hitl.reading import human_reading
from geni_studio.hitl.transaction import observation_mutation, run_mutation
from geni_studio.workspace.context import use_worktree
from geni_studio.workspace.layout import (
    prepare_run_layout,
    resolve_target_root,
    workspace_enabled,
)
from geni_studio.workspace.persist import persist_values

RunPhase = Literal[
    "running",
    "awaiting_human",
    "paused",
    "interrupted",
    "completed",
    "rejected",
    "stopped",
]
HitlKind = Literal["gate", "pm_clarification", "escalation"]
EscalationChoice = Literal["continue", "pause", "abort"]

_start_failures: dict[str, str] = {}
_start_failures_lock = threading.Lock()


@dataclass
class AwaitingHuman:
    kind: HitlKind
    since: str
    gate_id: str | None = None
    questions: list[str] = field(default_factory=list)
    summary: str = ""


@dataclass
class RunStatus:
    thread_id: str
    phase: RunPhase
    next_nodes: tuple[str, ...]
    awaiting_human: AwaitingHuman | None
    values: dict[str, Any]


class HitlError(ValueError):
    """HITL 状态或提交不合法。"""


class RunBusy(HitlError):
    """本轮已有检查点变更正在执行。"""


class StopPending(Exception):
    """停止已记下，检查点尚未建立或图仍在执行。"""

    def __init__(self, thread_id: str) -> None:
        self.thread_id = thread_id
        super().__init__(thread_id)


class GraphRunService:
    """对单一已编译图提供启动、查询与 HITL 续跑。"""

    @staticmethod
    def start_failure_message(thread_id: str) -> str | None:
        with _start_failures_lock:
            return _start_failures.get(thread_id)

    @staticmethod
    def _record_start_failure(thread_id: str, exc: BaseException) -> None:
        from geni_studio.workspace.layout import WorkspaceError

        msg = str(exc) if isinstance(exc, (WorkspaceError, ConfigError, ValueError)) else str(exc) or type(exc).__name__
        with _start_failures_lock:
            _start_failures[thread_id] = msg

    @staticmethod
    def _clear_start_failure(thread_id: str) -> None:
        with _start_failures_lock:
            _start_failures.pop(thread_id, None)

    def __init__(self, compiled_graph: CompiledStateGraph) -> None:
        self._graph = compiled_graph
        self._graphs: dict[str, CompiledStateGraph] = {}

    def _bound(self, thread_id: str) -> CompiledStateGraph:
        """未选流程时用默认图。选定流程的轮次用那张编译图。"""
        found = self._graphs.get(thread_id)
        if found is not None:
            return found
        snap = self._graph.get_state(self._config(thread_id))
        workflow_id = str((snap.values or {}).get("workflow_id") or "").strip()
        if not workflow_id:
            return self._graph
        definition = (snap.values or {}).get("workflow_definition")
        if not isinstance(definition, dict):
            # 允许历史记录查询、停止和删除；恢复前另外检查定义快照。
            return self._graph
        from geni_studio.workflows.executable import compile_workflow

        compiled = compile_workflow(definition, checkpointer=self._graph.checkpointer)
        self._graphs[thread_id] = compiled
        return compiled

    def _require_resume_definition(self, thread_id: str) -> None:
        values = self._graph.get_state(self._config(thread_id)).values or {}
        if values.get("workflow_id") and not isinstance(values.get("workflow_definition"), dict):
            raise HitlError("历史 Run 缺少流程定义快照，无法安全续跑，请新建一轮")

    @staticmethod
    def new_thread_id() -> str:
        return str(uuid.uuid4())

    def _config(self, thread_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": thread_id}}

    def _worktree_for(self, thread_id: str, payload: dict[str, Any] | None) -> str:
        if payload and payload.get("workspace_path"):
            return str(payload["workspace_path"])
        try:
            return str(self.status(thread_id).values.get("workspace_path") or "")
        except HitlError:
            return ""

    @run_mutation
    def _invoke(self, thread_id: str, payload: dict[str, Any] | None) -> None:
        if payload is None:
            self._require_resume_definition(thread_id)
        from geni_studio.hitl.control import (
            bind_thread,
            enter_inflight,
            is_pause_requested,
            is_stop_requested,
            leave_inflight,
            unbind_thread,
        )

        token = bind_thread(thread_id)
        already = enter_inflight(thread_id)
        try:
            if already:
                self._stop_before_invoke(thread_id, payload)
                return
            try:
                self._invoke_body(thread_id, payload)
            except Exception as exc:
                from geni_studio.hitl.control import RunPaused, RunStopped

                if not isinstance(exc, (RunPaused, RunStopped)) and not is_stop_requested(thread_id):
                    self._mark_interrupted(thread_id)
                    raise
        finally:
            leave_inflight(thread_id)
            unbind_thread(token)
        if is_stop_requested(thread_id):
            self._finish_stop(thread_id)
        elif is_pause_requested(thread_id):
            self._finish_pause(thread_id)

    def _stop_before_invoke(self, thread_id: str, payload: dict[str, Any] | None) -> None:
        try:
            self.status(thread_id)
        except HitlError:
            if payload is None:
                return
            self._seed_stopped(thread_id, payload)
            return
        self._finish_stop(thread_id)

    def _invoke_body(self, thread_id: str, payload: dict[str, Any] | None) -> None:
        path = self._worktree_for(thread_id, payload)
        project_id = ""
        if payload and payload.get("project_id"):
            project_id = str(payload["project_id"])
        elif path or payload is None:
            try:
                project_id = str(self.status(thread_id).values.get("project_id") or "")
            except HitlError:
                project_id = ""
        ctx = use_worktree(path) if path else nullcontext()
        lock_root = None
        if path:
            from geni_studio.workspace.layout import workspace_lock_root

            lock_root = workspace_lock_root(path)
        from geni_studio.workspace.policy import exclusive_write

        write_lock = exclusive_write(lock_root) if lock_root is not None else nullcontext()
        models: dict[str, str] = {}
        if isinstance(payload, dict) and isinstance(payload.get("role_models"), dict):
            models = payload["role_models"]
        else:
            try:
                stored = self.status(thread_id).values.get("role_models")
            except HitlError:
                stored = {}
            if isinstance(stored, dict):
                models = stored
        from geni_studio.backends.runner import reset_role_models, set_role_models

        project_token = set_project_id(project_id)
        role_token = set_role_models(models)
        cost_token = begin_cost_log()
        from geni_studio.backends.runtime import use_config

        state = payload if payload is not None else self.status(thread_id).values
        try:
            with write_lock, ctx, use_config(state.get("config_snapshot_effective")):
                self._bound(thread_id).invoke(payload, self._config(thread_id))
        finally:
            lines = take_cost_lines()
            end_cost_log(cost_token)
            reset_role_models(role_token)
            reset_project_id(project_token)
        self._append_costs(thread_id, lines)

    def _append_costs(self, thread_id: str, lines: list[str]) -> None:
        if not lines:
            return
        try:
            prior = str(self.status(thread_id).values.get("cost_ledger") or "")
        except HitlError:
            return
        # 相同 token 用量可能来自不同调用，不能用整行相等来去重。
        merged = (prior + "\n" + "\n".join(lines)).strip()
        self._bound(thread_id).update_state(self._config(thread_id), {"cost_ledger": merged})

    def _done(self, thread_id: str) -> RunStatus:
        st = self.status(thread_id)
        if workspace_enabled():
            run_dir = _run_dir_for(st.values, thread_id)
            if run_dir is not None:
                persist_values(
                    run_dir=run_dir,
                    thread_id=thread_id,
                    phase=st.phase,
                    values=st.values,
                )
        return st

    @staticmethod
    def _infer_awaiting(
        next_nodes: tuple[str, ...],
        values: dict[str, Any],
    ) -> AwaitingHuman | None:
        pending = str(values.get("hitl_pending_kind") or "").strip()
        if pending in ("pm_clarification", "escalation"):
            qs = values.get("hitl_questions") or []
            questions = [str(q) for q in qs] if isinstance(qs, list) else []
            return AwaitingHuman(
                kind=pending,  # type: ignore[arg-type]
                since=str(values.get("hitl_pending_since") or datetime.now(UTC).isoformat()),
                questions=questions,
                summary=str(values.get("hitl_summary") or ""),
            )
        if not next_nodes:
            return None
        head = next_nodes[0]
        gates = values.get("workflow_gates") or []
        if head in GATE_NODES or (isinstance(gates, list) and head in gates):
            since = str(values.get("awaiting_since") or "").strip() or datetime.now(UTC).isoformat()
            summary = _workflow_gate_summary(values, head) or gate_summary(head)
            note = str(values.get("gate_timeout_note") or "").strip()
            if note:
                summary = f"{summary} {note}"
            return AwaitingHuman(
                kind="gate",
                since=since,
                gate_id=head,
                summary=summary,
            )
        return None

    @staticmethod
    def _phase(
        next_nodes: tuple[str, ...],
        values: dict[str, Any],
        awaiting: AwaitingHuman | None,
    ) -> RunPhase:
        if values.get("run_stopped"):
            return "stopped"
        if values.get("run_interrupted"):
            return "interrupted"
        if awaiting is not None:
            return "awaiting_human"
        if values.get("run_paused"):
            return "paused"
        if values.get("last_gate_decision") == "rejected" and not next_nodes:
            return "rejected"
        if not next_nodes:
            return "completed"
        return "running"

    def status(self, thread_id: str) -> RunStatus:
        cfg = self._config(thread_id)
        snap = self._bound(thread_id).get_state(cfg)
        if not snap.values and not snap.next:
            raise HitlError(f"未知 thread_id={thread_id!r}")
        next_nodes = tuple(snap.next or ())
        values = dict(snap.values or {})
        awaiting = self._infer_awaiting(next_nodes, values)
        phase = self._phase(next_nodes, values, awaiting)
        return RunStatus(
            thread_id=thread_id,
            phase=phase,
            next_nodes=next_nodes,
            awaiting_human=awaiting,
            values=values,
        )

    def _prepare_start(
        self,
        *,
        human_request: str,
        scenario_key: str = "",
        project_id: str = "",
        thread_id: str | None = None,
        run_name: str = "",
        node_tools: dict[str, dict[str, list[str]]] | None = None,
        attachment_ids: list[str] | None = None,
        role_models: dict[str, str] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        from geni_studio.config.context import build_run_context, factory_root
        from geni_studio.config.precheck import precheck_scenario_materials
        from geni_studio.config.snapshot import capture_config_snapshot
        from geni_studio.hitl.run_name import assign_run_name, taken_names_for_project

        precheck_scenario_materials(scenario_key, project_id)
        tid = thread_id or self.new_thread_id()
        taken = taken_names_for_project(latest_run_records(self._graph), project_id)
        snap = capture_config_snapshot(scenario_key, project_id)
        ctx = build_run_context(
            scenario_key=snap["scenario_key"] or scenario_key,
            project_id=snap["project_id"] or project_id,
        )
        import os
        from copy import deepcopy

        from geni_studio.backends.base import factory_default_model

        effective = deepcopy(ctx.merged)
        effective["_backend"] = os.environ.get("GENI_STUDIO_BACKEND", "").strip().lower() or "cursor"
        effective["_models"] = {name: factory_default_model(name) for name in ("cursor", "codex", "stub")}
        effective["_test_command"] = str(
            os.environ.get("GENI_STUDIO_TEST_COMMAND")
            or (ctx.merged.get("verification") or {}).get("command") or ""
        )
        effective["_roles"] = {
            path.parent.name: path.read_text(encoding="utf-8")
            for path in (factory_root() / "roles").glob("*/role.md")
        }
        initial: dict[str, Any] = {
            "human_request": human_request,
            "run_name": assign_run_name(snap["project_id"] or project_id, run_name, taken),
            "finance_enabled": ctx.feature_finance(),
            "project_id": snap.get("project_id") or project_id,
            "scenario_key": snap.get("scenario_key") or scenario_key,
            **snap,
            "config_snapshot_effective": effective,
        }
        profile = ctx.profile_id.strip()
        from geni_studio.config.workflow_defs import (
            uses_current_branch,
            uses_default_engine,
            workflow_exists,
        )

        root = factory_root()
        direct_branch = uses_current_branch(profile, root)
        if profile and workflow_exists(profile, root) and not uses_default_engine(profile, root):
            from geni_studio.workflows.executable import compile_for_project

            compiled, extra = compile_for_project(
                profile,
                checkpointer=self._graph.checkpointer,
                root=root,
            )
            self._graphs[tid] = compiled
            initial.update(extra)
        if workspace_enabled():
            layout = prepare_run_layout(
                resolve_target_root(project_id),
                tid,
                on_current_branch=direct_branch,
            )
            initial["workspace_path"] = str(layout.worktree)
            if layout.base_branch:
                initial["base_branch"] = layout.base_branch
        if node_tools:
            initial["node_tools"] = node_tools
        if role_models:
            initial["role_models"] = role_models
        if attachment_ids:
            from pathlib import Path

            from geni_studio.hitl.attachments import stage_attachments

            if direct_branch and initial.get("workspace_path"):
                base = Path(initial["workspace_path"]) / ".geni_studio" / "runs" / tid
                relative = stage_attachments(attachment_ids, base / "attachments")
                initial["attachments"] = [
                    str(Path(".geni_studio") / "runs" / tid / "attachments" / Path(item).name)
                    for item in relative
                ]
            else:
                base = Path(initial["workspace_path"]) if initial.get("workspace_path") else root / "runs" / "inbox" / tid
                relative = stage_attachments(attachment_ids, base / "attachments")
                if initial.get("workspace_path"):
                    initial["attachments"] = relative
                else:
                    initial["attachments"] = [str(base / "attachments" / Path(item).name) for item in relative]
        return tid, initial

    def start(
        self,
        *,
        human_request: str,
        scenario_key: str = "",
        project_id: str = "",
        thread_id: str | None = None,
        run_name: str = "",
        node_tools: dict[str, dict[str, list[str]]] | None = None,
        attachment_ids: list[str] | None = None,
        role_models: dict[str, str] | None = None,
    ) -> RunStatus:
        tid, initial = self._prepare_start(
            human_request=human_request,
            scenario_key=scenario_key,
            project_id=project_id,
            thread_id=thread_id,
            run_name=run_name,
            node_tools=node_tools,
            attachment_ids=attachment_ids,
            role_models=role_models,
        )
        from geni_studio.workspace.layout import workspace_lock_root
        from geni_studio.workspace.policy import assert_write_available

        lock_root = workspace_lock_root(str(initial.get("workspace_path") or ""))
        if lock_root is not None:
            assert_write_available(lock_root)
        self._invoke(tid, initial)
        return self._done(tid)

    def enqueue_start(
        self,
        *,
        human_request: str,
        scenario_key: str = "",
        project_id: str = "",
        thread_id: str | None = None,
        run_name: str = "",
        node_tools: dict[str, dict[str, list[str]]] | None = None,
        attachment_ids: list[str] | None = None,
        role_models: dict[str, str] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """在后台执行图 invoke，HTTP 可立即返回 thread_id。"""
        import threading

        from geni_studio.hitl.control import clear_starting, mark_starting

        tid, initial = self._prepare_start(
            human_request=human_request,
            scenario_key=scenario_key,
            project_id=project_id,
            thread_id=thread_id,
            run_name=run_name,
            node_tools=node_tools,
            attachment_ids=attachment_ids,
            role_models=role_models,
        )
        from geni_studio.workspace.layout import workspace_lock_root
        from geni_studio.workspace.policy import assert_write_available

        path = str(initial.get("workspace_path") or "")
        lock_root = workspace_lock_root(path)
        if lock_root is not None:
            assert_write_available(lock_root)

        mark_starting(tid)
        self._clear_start_failure(tid)

        def work() -> None:
            try:
                self._invoke(tid, initial)
                self._clear_start_failure(tid)
            except Exception as exc:  # noqa: BLE001 — 后台线程必须记录失败，供状态接口查询。
                self._record_start_failure(tid, exc)
            finally:
                clear_starting(tid)

        threading.Thread(target=work, name=f"geni-start-{tid[:8]}", daemon=True).start()
        return tid, initial

    def provisional_status_dict(self, thread_id: str, initial: dict[str, Any]) -> dict[str, Any]:
        """检查点尚未写入时，给前端一帧运行中状态。"""
        st = RunStatus(
            thread_id=thread_id,
            phase="running",
            next_nodes=("project_manager_draft",),
            awaiting_human=None,
            values=dict(initial),
        )
        ah = st.awaiting_human
        reading, choices, choice_groups = _reading_and_choices(ah, st.values)
        return {
            "thread_id": st.thread_id,
            "phase": st.phase,
            "stop_requested": False,
            "pause_requested": False,
            "next_nodes": list(st.next_nodes),
            "awaiting_human": None,
            "values": _public_values(st.values),
            "limits": {"max_dev_retries": _dev_retry_limit(st.values)},
            "rail": _rail_for(st),
            "reading": reading,
            "choices": choices,
            "choice_groups": choice_groups,
        }

    @run_mutation
    def set_node_tools(
        self,
        thread_id: str,
        node_id: str,
        *,
        skills: list[str],
        mcp: list[str],
    ) -> RunStatus:
        """记下这一轮、这一个节点选用的 Skill 和 MCP。"""
        st = self.status(thread_id)
        if st.phase in ("completed", "rejected", "stopped"):
            raise HitlError("这一轮已经结束。")
        current = st.values.get("node_tools")
        chosen = dict(current) if isinstance(current, dict) else {}
        if skills or mcp:
            chosen[node_id] = {"skills": skills, "mcp": mcp}
        else:
            chosen.pop(node_id, None)
        self._bound(thread_id).update_state(self._config(thread_id), {"node_tools": chosen})
        return self._done(thread_id)

    @run_mutation
    def set_role_models(self, thread_id: str, role_models: dict[str, str]) -> RunStatus:
        """记下这一轮各角色选用的模型。"""
        st = self.status(thread_id)
        if st.phase in ("completed", "rejected", "stopped"):
            raise HitlError("这一轮已经结束。")
        self._bound(thread_id).update_state(self._config(thread_id), {"role_models": role_models})
        return self._done(thread_id)

    def advance_until_blocked(self, thread_id: str) -> RunStatus:
        cfg = self._config(thread_id)
        while True:
            snap = self._bound(thread_id).get_state(cfg)
            values = dict(snap.values or {})
            if values.get("hitl_pending_kind"):
                break
            next_nodes = tuple(snap.next or ())
            if not next_nodes:
                break
            gates = values.get("workflow_gates") or []
            if next_nodes[0] in GATE_NODES or (isinstance(gates, list) and next_nodes[0] in gates):
                break
            self._invoke(thread_id, None)
        return self._done(thread_id)

    @run_mutation
    def open_hitl(
        self,
        thread_id: str,
        *,
        kind: Literal["pm_clarification", "escalation"],
        questions: list[str] | None = None,
        summary: str = "",
    ) -> RunStatus:
        st = self.status(thread_id)
        if st.phase in ("completed", "rejected", "stopped"):
            raise HitlError(f"Run 已结束（phase={st.phase}），无法打开 HITL")
        cfg = self._config(thread_id)
        patch: dict[str, Any] = {
            "hitl_pending_kind": kind,
            "hitl_questions": questions or [],
            "hitl_summary": summary,
            "hitl_pending_since": datetime.now(UTC).isoformat(),
        }
        self._bound(thread_id).update_state(cfg, patch)
        return self._done(thread_id)

    def _clear_pending_patch(self) -> dict[str, Any]:
        return {
            "hitl_pending_kind": None,
            "hitl_questions": [],
            "hitl_summary": "",
            "hitl_pending_since": None,
        }

    @run_mutation
    def submit_hitl(
        self,
        thread_id: str,
        *,
        gate_decision: Literal["approved", "rejected"] | None = None,
        human_reply: str = "",
        channel: str = "web",
        escalation_choice: EscalationChoice | None = None,
    ) -> RunStatus:
        st = self.status(thread_id)
        if st.phase != "awaiting_human" or st.awaiting_human is None:
            raise HitlError("当前 Run 不在 awaiting_human，无法提交 HITL")
        self._require_resume_definition(thread_id)
        awaiting = st.awaiting_human
        cfg = self._config(thread_id)
        audit = audit_patch(
            st.values,
            channel=channel,
            kind=awaiting.kind,
            thread_id=thread_id,
            summary=awaiting.summary,
            gate_decision=gate_decision,
            human_reply=human_reply,
        )

        if awaiting.kind == "gate":
            if gate_decision not in ("approved", "rejected"):
                raise HitlError("gate 待办须提供 gate_decision: approved | rejected")
            patch: dict[str, Any] = {
                "gate_decision": gate_decision,
                "human_reply": human_reply,
                **audit,
            }
            self._bound(thread_id).update_state(cfg, patch)
            self._invoke(thread_id, None)
            return self._done(thread_id)

        if awaiting.kind == "pm_clarification":
            if not human_reply.strip():
                raise HitlError("pm_clarification 须填写 human_reply")
            spec = str(st.values.get("requirement_spec") or "")
            merged_spec = merge_clarification_reply(
                spec,
                human_reply,
                questions=awaiting.questions,
            )
            patch = {
                "requirement_spec": merged_spec,
                "human_reply": human_reply,
                "hitl_clarification_resolved": True,
                **self._clear_pending_patch(),
                **audit,
            }
            self._bound(thread_id).update_state(cfg, patch)
            snap = self._bound(thread_id).get_state(cfg)
            if not snap.next:
                self._bound(thread_id).update_state(cfg, None, as_node="tester_testability")
            # 澄清答复只解决提问，不等同于批准当前或即将进入的关卡。
            snap = self._bound(thread_id).get_state(cfg)
            gates = set(GATE_NODES) | set(snap.values.get("workflow_gates") or [])
            if not any(node in gates for node in snap.next):
                self._invoke(thread_id, None)
            return self._done(thread_id)

        if awaiting.kind == "escalation":
            choice = escalation_choice
            if not choice and human_reply.strip() in ("continue", "pause", "abort"):
                choice = human_reply.strip()  # type: ignore[assignment]
            if choice not in ("continue", "pause", "abort"):
                raise HitlError(
                    "escalation 须提供 escalation_choice: continue | pause | abort"
                )
            patch = {
                "human_reply": human_reply or choice,
                "escalation_choice": choice,
                **self._clear_pending_patch(),
                **audit,
            }
            self._bound(thread_id).update_state(cfg, patch)
            if choice == "continue":
                snap = self._bound(thread_id).get_state(cfg)
                if not snap.next:
                    resume_at = str(st.values.get("escalated_from") or "developer")
                    if resume_at not in self._bound(thread_id).nodes:
                        resume_at = "developer"
                    self._bound(thread_id).update_state(cfg, None, as_node=resume_at)
                self._invoke(thread_id, None)
            return self._done(thread_id)

        raise HitlError(f"未知 kind={awaiting.kind!r}")

    def submit_from_feishu_card(
        self,
        *,
        thread_id: str,
        gate_decision: Literal["approved", "rejected"] | None = None,
        human_reply: str = "",
        escalation_choice: EscalationChoice | None = None,
    ) -> RunStatus:
        if escalation_choice is not None:
            return self.submit_hitl(
                thread_id,
                human_reply=human_reply,
                escalation_choice=escalation_choice,
                channel="feishu",
            )
        if gate_decision not in ("approved", "rejected"):
            raise HitlError("gate 卡片回调缺少 gate_decision")
        return self.submit_hitl(
            thread_id,
            gate_decision=gate_decision,
            human_reply=human_reply,
            channel="feishu",
        )

    def stop(self, thread_id: str, *, channel: str = "web") -> RunStatus:
        from geni_studio.hitl.control import (
            cancel_active_runs,
            clear_stop_request,
            request_stop,
        )

        busy = request_stop(thread_id)
        cancel_active_runs(thread_id)
        if busy:
            try:
                return self.status(thread_id)
            except HitlError as exc:
                raise StopPending(thread_id) from exc
        try:
            st = self.status(thread_id)
        except HitlError as exc:
            raise StopPending(thread_id) from exc
        if st.phase in ("completed", "rejected"):
            clear_stop_request(thread_id)
            raise HitlError(f"Run 已结束（phase={st.phase}），无法停止")
        if st.phase == "stopped":
            clear_stop_request(thread_id)
            return st
        return self._finish_stop(thread_id, channel=channel)

    def pause(self, thread_id: str) -> RunStatus:
        """暂停本轮。不结束检查点，已完成的节点保持完成。"""
        from geni_studio.hitl.control import request_pause

        st = self.status(thread_id)
        if st.phase == "paused":
            return st
        if st.phase != "running":
            raise HitlError(f"当前阶段是{st.phase}，不能暂停")
        busy = request_pause(thread_id)
        if busy:
            return self.status(thread_id)
        return self._finish_pause(thread_id)

    @run_mutation
    def resume(self, thread_id: str) -> RunStatus:
        """从暂停的节点继续，不重做已完成节点。"""
        from geni_studio.hitl.control import clear_pause_request

        st = self.status(thread_id)
        if st.phase != "paused":
            raise HitlError(f"当前阶段是{st.phase}，不能继续")
        self._require_resume_definition(thread_id)
        clear_pause_request(thread_id)
        self._bound(thread_id).update_state(
            self._config(thread_id),
            {"run_paused": False, "paused_at": ""},
        )
        self._invoke(thread_id, None)
        return self._done(thread_id)

    @run_mutation
    def continue_interrupted(self, thread_id: str) -> RunStatus:
        """从中断的节点接着做，不重做已完成的节点。"""
        st = self.status(thread_id)
        if st.phase != "interrupted":
            raise HitlError(f"当前阶段是{st.phase}，不能续跑")
        self._require_resume_definition(thread_id)
        self._bound(thread_id).update_state(
            self._config(thread_id),
            {"run_interrupted": False, "interrupted_at": ""},
        )
        self._invoke(thread_id, None)
        return self._done(thread_id)

    def _mark_interrupted(self, thread_id: str) -> None:
        try:
            snap = self._bound(thread_id).get_state(self._config(thread_id))
        except Exception:  # noqa: BLE001 — 检查点还没写好时无法标记中断
            return
        if not snap.values and not snap.next:
            return
        next_nodes = tuple(snap.next or ())
        node = next_nodes[0] if next_nodes else ""
        self._bound(thread_id).update_state(
            self._config(thread_id),
            {"run_interrupted": True, "interrupted_at": node},
        )

    def _finish_pause(self, thread_id: str) -> RunStatus:
        from geni_studio.hitl.control import clear_pause_request

        try:
            st = self.status(thread_id)
        except HitlError:
            clear_pause_request(thread_id)
            raise
        if st.phase != "running":
            clear_pause_request(thread_id)
            return st
        paused_at = st.next_nodes[0] if st.next_nodes else str(_rail_for(st).get("current") or "")
        self._bound(thread_id).update_state(
            self._config(thread_id),
            {"run_paused": True, "paused_at": paused_at},
        )
        clear_pause_request(thread_id)
        return self._done(thread_id)

    def _seed_stopped(self, thread_id: str, payload: dict[str, Any]) -> None:
        from langgraph.graph import END

        from geni_studio.hitl.control import clear_stop_request

        values = dict(payload)
        values["run_stopped"] = True
        values["stopped_at"] = ""
        cfg = self._config(thread_id)
        self._bound(thread_id).update_state(cfg, values, as_node="__start__")
        self._bound(thread_id).update_state(cfg, None, as_node=END)
        clear_stop_request(thread_id)

    def _finish_stop(self, thread_id: str, *, channel: str = "web") -> RunStatus:
        from langgraph.graph import END

        from geni_studio.hitl.control import clear_pause_request, clear_stop_request

        try:
            st = self.status(thread_id)
        except HitlError:
            self._seed_stopped(thread_id, {})
            clear_pause_request(thread_id)
            return self.status(thread_id)
        if st.phase in ("completed", "rejected", "stopped"):
            clear_stop_request(thread_id)
            clear_pause_request(thread_id)
            return st
        stopped_at = str(_rail_for(st).get("current") or "")
        as_node = "project_manager_draft"
        for name in st.next_nodes:
            if name in self._bound(thread_id).nodes:
                as_node = name
                break
        patch: dict[str, Any] = {
            "run_stopped": True,
            "run_paused": False,
            "run_interrupted": False,
            "interrupted_at": "",
            "stopped_at": stopped_at,
            **self._clear_pending_patch(),
            **audit_patch(
                st.values,
                channel=channel,
                kind="stop",
                thread_id=thread_id,
                summary="停止本轮",
            ),
        }
        cfg = self._config(thread_id)
        self._bound(thread_id).update_state(cfg, patch, as_node=as_node)
        self._bound(thread_id).update_state(cfg, None, as_node=END)
        clear_stop_request(thread_id)
        clear_pause_request(thread_id)
        return self._done(thread_id)

    def copy_run_template(self, thread_id: str) -> dict[str, Any]:
        """复制启动参数，用于新建一轮；不复制检查点进度与产物。"""
        from geni_studio.hitl.drafts import load_draft, taken_draft_names
        from geni_studio.hitl.run_name import assign_run_name, taken_names_for_project

        if "-" not in thread_id and len(thread_id) == 32 and thread_id.isalnum():
            try:
                draft = load_draft(thread_id)
            except HitlError:
                draft = None
            if draft is not None and draft.get("kind") == "draft":
                pid = str(draft.get("project_id") or "")
                taken = taken_names_for_project(latest_run_records(self._graph), pid)
                taken |= taken_draft_names(pid)
                base = str(draft.get("run_name") or "").strip()
                suffix = "·复制" if base else ""
                return {
                    "source_thread_id": thread_id,
                    "source_kind": "draft",
                    "source_phase": "saved",
                    "project_id": pid,
                    "scenario_key": "",
                    "human_request": str(draft.get("human_request") or ""),
                    "run_name": assign_run_name(pid, f"{base}{suffix}", taken),
                    "node_tools": dict(draft.get("node_tools") or {}),
                    "role_models": dict(draft.get("role_models") or {}),
                    "attachments": list(draft.get("attachments") or []),
                }
        st = self.status(thread_id)
        values = st.values or {}
        pid = str(values.get("project_id") or "")
        taken = taken_names_for_project(latest_run_records(self._graph), pid)
        taken |= taken_draft_names(pid)
        base = str(values.get("run_name") or "").strip()
        node_tools = values.get("node_tools")
        role_models = values.get("role_models")
        return {
            "source_thread_id": thread_id,
            "source_kind": "run",
            "source_phase": st.phase,
            "project_id": pid,
            "scenario_key": str(values.get("scenario_key") or ""),
            "human_request": str(values.get("human_request") or ""),
            "run_name": assign_run_name(pid, f"{base}·复制" if base else "", taken),
            "node_tools": dict(node_tools) if isinstance(node_tools, dict) else {},
            "role_models": dict(role_models) if isinstance(role_models, dict) else {},
            "attachments": [],
        }

    def list_runs(self, *, project_id: str = "", phase: str = "") -> list[dict[str, Any]]:
        """按检查点列出已有轮次。点进某一轮仍用原来的状态接口。"""
        rows: list[dict[str, Any]] = []
        want_project = project_id.strip()
        want_phase = phase.strip()
        for thread_id, _values in latest_run_records(self._graph):
            try:
                st = self._observe(thread_id)
            except HitlError:
                continue
            pid = str(st.values.get("project_id") or "")
            if want_project and pid != want_project:
                continue
            if want_phase and st.phase != want_phase:
                continue
            rail = _rail_for(st)
            rows.append(
                {
                    "thread_id": st.thread_id,
                    "run_name": str(st.values.get("run_name") or st.thread_id),
                    "phase": st.phase,
                    "project_id": pid,
                    "current": rail.get("current") or "",
                }
            )
        return rows

    @run_mutation
    def delete_run(self, thread_id: str, *, confirm_name: str) -> None:
        """删除一轮检查点。名称必须一致，运行中的一轮要先停止。"""
        from geni_studio.hitl.control import clear_pause_request, clear_stop_request

        st = self.status(thread_id)
        if st.phase == "running":
            raise HitlError("这一轮还在运行，先停止再删除。")
        expected = str(st.values.get("run_name") or thread_id).strip() or thread_id
        if confirm_name.strip() != expected:
            raise HitlError("名称不一致，没有删除。")
        saver = getattr(self._graph, "checkpointer", None)
        if saver is None or not hasattr(saver, "delete_thread"):
            raise HitlError("当前检查点不能删除这一轮。")
        saver.delete_thread(thread_id)
        self._graphs.pop(thread_id, None)
        clear_stop_request(thread_id)
        clear_pause_request(thread_id)

    @observation_mutation
    def note_gate_timeout(self, thread_id: str) -> RunStatus:
        """等待超过时限时记一笔未批复，关卡仍停在原地，不自动批准或驳回。"""
        st = self.status(thread_id)
        if st.awaiting_human is None or st.values.get("gate_timeout_recorded"):
            return st
        since = str(st.values.get("awaiting_since") or "").strip()
        if not since:
            since = datetime.now(UTC).isoformat()
            self._bound(thread_id).update_state(self._config(thread_id), {"awaiting_since": since})
            st = self.status(thread_id)
        limit = _gate_timeout_seconds()
        try:
            started = datetime.fromisoformat(since)
        except ValueError:
            return st
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        elapsed = (datetime.now(UTC) - started).total_seconds()
        if limit > 0 and elapsed < limit:
            return st
        note = "超时未批复。本轮仍停在关卡上，不自动批准或驳回。"
        audit = str(st.values.get("hitl_audit_log") or "").strip()
        line = f"[timeout] {note}"
        if line not in audit:
            audit = f"{audit}\n{line}".strip()
        self._bound(thread_id).update_state(
            self._config(thread_id),
            {
                "gate_timeout_recorded": True,
                "gate_timeout_note": note,
                "hitl_audit_log": audit,
            },
        )
        return self.status(thread_id)

    @observation_mutation
    def _observe(self, thread_id: str) -> RunStatus:
        """对外查看时，把已经没有执行体的运行中轮次记为中断。"""
        from geni_studio.hitl.control import (
            is_inflight,
            is_pause_requested,
            is_starting,
            is_stop_requested,
        )

        st = self.status(thread_id)

        if (
            st.phase == "running"
            and not is_inflight(thread_id)
            and not is_starting(thread_id)
            and not is_pause_requested(thread_id)
            and not is_stop_requested(thread_id)
        ):
            self._mark_interrupted(thread_id)
            st = self.status(thread_id)
        return st

    def status_dict(self, thread_id: str) -> dict[str, Any]:
        st = self.note_gate_timeout(thread_id)
        if st.phase == "running":
            st = self._observe(thread_id)
        ah = st.awaiting_human
        reading, choices, choice_groups = _reading_and_choices(ah, st.values)
        return {
            "thread_id": st.thread_id,
            "phase": st.phase,
            "stop_requested": _stop_requested(st.thread_id),
            "pause_requested": _pause_requested(st.thread_id),
            "next_nodes": list(st.next_nodes),
            "awaiting_human": (
                {
                    "kind": ah.kind,
                    "since": ah.since,
                    "gate_id": ah.gate_id,
                    "questions": ah.questions,
                    "summary": ah.summary,
                }
                if ah
                else None
            ),
            "values": _public_values(st.values),
            "limits": {"max_dev_retries": _dev_retry_limit(st.values)},
            "rail": _rail_for(st),
            "reading": reading,
            "choices": choices,
            "choice_groups": choice_groups,
        }


def _reading_and_choices(
    ah: Any, values: dict[str, Any]
) -> tuple[list[dict[str, str]], list[dict[str, Any]], list[dict[str, Any]]]:
    reading = human_reading(
        {
            "kind": ah.kind,
            "gate_id": ah.gate_id,
            "questions": ah.questions,
            "summary": ah.summary,
        }
        if ah
        else None,
        values,
    )
    choices = choices_from_reading(reading)
    return reading, choices, choice_groups_from_reading(reading)


def _stop_requested(thread_id: str) -> bool:
    from geni_studio.hitl.control import is_stop_requested

    return is_stop_requested(thread_id)


def _pause_requested(thread_id: str) -> bool:
    from geni_studio.hitl.control import is_pause_requested

    return is_pause_requested(thread_id)


def _gate_timeout_seconds() -> float:
    import os

    raw = os.environ.get("GENI_STUDIO_GATE_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return 24 * 60 * 60
    try:
        return float(raw)
    except ValueError:
        return 24 * 60 * 60


def _dev_retry_limit(values: dict[str, Any]) -> int:
    from geni_studio.workflows.default import max_dev_retries_for_state

    return max_dev_retries_for_state(values)


def _rail_for(st: RunStatus) -> dict[str, Any]:
    values = st.values or {}
    skip: set[str] | None = None
    if str(values.get("scenario_key") or "").strip() or str(values.get("project_id") or "").strip():
        try:
            ctx = build_run_context_from_state(values)
            from geni_studio.config.workflow_nodes import nodes_hidden_from_rail

            skip = nodes_hidden_from_rail(
                skip_nodes=ctx.skip_nodes,
                finance_enabled=ctx.feature_finance(),
            )
        except ConfigError:
            skip = None
    awaiting = None
    if st.awaiting_human is not None:
        ah = st.awaiting_human
        awaiting = {
            "kind": ah.kind,
            "gate_id": ah.gate_id,
            "summary": ah.summary,
            "from_node": str(values.get("escalated_from") or ""),
        }
    catalog, meta = _workflow_catalog(values)
    if catalog:
        skip = set()
    return build_rail(
        phase=st.phase,
        next_nodes=st.next_nodes,
        awaiting=awaiting,
        skip_nodes=skip,
        baseline_log=str(values.get("baseline_log") or ""),
        stopped_at=str(values.get("stopped_at") or ""),
        paused_at=(
            str(values.get("interrupted_at") or (st.next_nodes[0] if st.next_nodes else ""))
            if st.phase == "interrupted"
            else str(values.get("paused_at") or "")
        ),
        catalog=catalog,
        meta=meta,
    )


def _workflow_catalog(
    values: dict[str, Any],
) -> tuple[tuple[tuple[str, str], ...] | None, dict[str, dict[str, Any]] | None]:
    raw = values.get("workflow_nodes")
    if not isinstance(raw, list) or not raw:
        return None, None
    items: list[tuple[str, str]] = []
    meta: dict[str, dict[str, Any]] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        node_id = str(item.get("id") or "").strip()
        if not node_id:
            continue
        items.append((node_id, str(item.get("label") or node_id)))
        meta[node_id] = item
    if not items:
        return None, None
    return tuple(items), meta


def _workflow_gate_summary(values: dict[str, Any], gate_id: str) -> str:
    raw = values.get("workflow_nodes")
    if not isinstance(raw, list):
        return ""
    for item in raw:
        if isinstance(item, dict) and str(item.get("id") or "") == gate_id:
            name = str(item.get("label") or gate_id)
            reject_id = str(item.get("reject_to") or "").strip()
            reject_name = ""
            if reject_id:
                for other in raw:
                    if isinstance(other, dict) and str(other.get("id") or "") == reject_id:
                        reject_name = str(other.get("label") or reject_id)
                        break
            if reject_name:
                return f"{name}：请批准，或不通过并前往「{reject_name}」。"
            return f"{name}：请批准，或不通过以结束本轮。"
    return ""


def _run_dir_for(values: dict[str, Any], thread_id: str):
    from geni_studio.workspace.layout import run_dir_for_workspace

    return run_dir_for_workspace(str(values.get("workspace_path") or ""), thread_id)


def latest_run_records(graph) -> list[tuple[str, dict[str, Any]]]:
    """每个 thread 只取最新检查点，用来给同一项目递增 Run 序号。"""
    saver = getattr(graph, "checkpointer", None)
    if saver is None:
        return []
    seen: set[str] = set()
    records: list[tuple[str, dict[str, Any]]] = []
    for item in saver.list(None):
        configurable = (item.config or {}).get("configurable") or {}
        thread_id = str(configurable.get("thread_id") or "")
        namespace = str(configurable.get("checkpoint_ns") or "")
        if not thread_id or namespace or thread_id in seen:
            continue
        values = (item.checkpoint or {}).get("channel_values") or {}
        if not isinstance(values, dict):
            continue
        seen.add(thread_id)
        records.append((thread_id, values))
    return records


def _public_values(values: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, val in values.items():
        if key in {"workflow_definition", "config_snapshot_effective"}:
            continue
        if val is None:
            continue
        if isinstance(val, str) and len(val) > 2000:
            out[key] = val[:2000] + "…"
        else:
            out[key] = val
    return out
