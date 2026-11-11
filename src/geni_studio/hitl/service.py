"""LangGraph Run 与 HITL 提交（Web / 飞书共用）。"""

from __future__ import annotations

import threading
import uuid
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from langgraph.graph.state import CompiledStateGraph

from geni_studio.backends.cost import (
    begin_cost_log,
    end_cost_log,
    reset_project_id,
    set_project_id,
    take_cost_lines,
)
from geni_studio.hitl import presenter
from geni_studio.hitl.constants import GATE_NODES, gate_summary
from geni_studio.hitl.hitl_audit import audit_patch
from geni_studio.hitl.pm_clarification import merge_clarification_reply
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

_GRAPH_CACHE_SIZE = 64
# 同步调用路径不等待写锁；后台执行器领取任务时另行设置等待时长。
_WRITE_LOCK_WAIT_SECONDS = 0.0


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


class RunNotFound(HitlError):
    """运行或草稿不存在。"""


class RunConflict(HitlError):
    """请求与运行当前状态冲突。"""


class NotAwaiting(RunConflict):
    """本轮不在等待人的决定。"""


class RunBusy(RunConflict):
    """本轮已有检查点变更正在执行。"""


class StopPending(Exception):
    """停止已记下，检查点尚未建立或图仍在执行。"""

    def __init__(self, thread_id: str) -> None:
        self.thread_id = thread_id
        super().__init__(thread_id)


class GraphRunService:
    """对单一已编译图提供启动、查询与 HITL 续跑。"""

    def __init__(self, compiled_graph: CompiledStateGraph) -> None:
        from collections import OrderedDict

        self._graph = compiled_graph
        self._graphs: OrderedDict[str, CompiledStateGraph] = OrderedDict()
        self._graphs_lock = threading.Lock()
        self._store = None
        self._executor = None
        self._executor_lock = threading.Lock()

    # --- 运行时：任务表、执行器、索引 ---

    def runtime_store(self):
        if self._store is None:
            from geni_studio.runtime.store import store_for_saver

            self._store = store_for_saver(self._graph.checkpointer)
        return self._store

    def executor(self):
        from geni_studio.runtime.executor import Executor, executor_mode

        with self._executor_lock:
            if self._executor is None:
                self._executor = Executor(self)
            if executor_mode() == "thread":
                self._executor.start()
            return self._executor

    def _dispatch(self, thread_id: str, kind: str, payload: Any = None) -> None:
        """入队一个推进任务。inline 模式在当前线程执行，其余模式交给执行器。"""
        self._kick(self._enqueue(thread_id, kind, payload))

    def _enqueue(self, thread_id: str, kind: str, payload: Any = None):
        store = self.runtime_store()
        store.set_meta(_notice_key(thread_id), "")
        job = store.enqueue(thread_id, kind, payload)
        self.notify_change(thread_id)
        return job

    def _kick(self, job) -> None:
        from geni_studio.runtime.executor import executor_mode

        if job is None:
            return
        mode = executor_mode()
        if mode == "external":
            return
        executor = self.executor()
        if mode == "inline":
            executor.run_once(job_id=job.id)
        else:
            executor.wake()

    def _sync_controls(self, thread_id: str) -> None:
        from geni_studio.hitl.control import request_pause, request_stop

        stop, pause = self.runtime_store().controls(thread_id)
        if stop:
            request_stop(thread_id)
        elif pause:
            request_pause(thread_id)

    def execute_job(self, job) -> None:
        self._sync_controls(job.thread_id)
        if job.kind == "start":
            self._invoke(job.thread_id, job.payload)
        elif job.kind == "invoke":
            self._invoke(job.thread_id, None)
        else:
            raise HitlError(f"未知任务类型：{job.kind}")
        self._done(job.thread_id)

    def after_job(self, thread_id: str, *, notify: bool = True) -> None:
        """任务出队后刷新索引与事件；停在人工节点时发飞书通知。"""
        try:
            st = self.status(thread_id)
        except HitlError:
            self.notify_change(thread_id)
            return
        self._index(thread_id, st)
        self.notify_change(thread_id)
        if not notify or st.phase != "awaiting_human":
            return
        from geni_studio.hitl.feishu_notify import notify_awaiting_human_via_lark_cli

        try:
            result = notify_awaiting_human_via_lark_cli(self, thread_id, str(st.values.get("project_id") or ""))
        except Exception as exc:
            import logging

            logging.getLogger(__name__).exception("飞书通知失败 thread=%s", thread_id)
            result_notice = {"sent": False, "detail": f"飞书通知失败：{exc}"}
        else:
            if not (result.sent or result.detail):
                return
            result_notice = {"sent": result.sent, "detail": result.detail}
        import json

        self.runtime_store().set_meta(_notice_key(thread_id), json.dumps(result_notice, ensure_ascii=False))

    def feishu_notice(self, thread_id: str) -> dict[str, Any] | None:
        """最近一次推进后发出的飞书通知结果；新任务入队时清空。"""
        import json

        raw = self.runtime_store().meta(_notice_key(thread_id))
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    @staticmethod
    def notify_change(thread_id: str) -> None:
        from geni_studio.runtime.events import bump

        bump(thread_id)

    def _job_active(self, thread_id: str):
        return self.runtime_store().active_job(thread_id)

    def _is_active(self, thread_id: str) -> bool:
        from geni_studio.hitl.control import (
            is_inflight,
            is_pause_requested,
            is_starting,
            is_stop_requested,
        )
        from geni_studio.hitl.transaction import is_mutating

        return (
            is_inflight(thread_id)
            or is_starting(thread_id)
            or is_pause_requested(thread_id)
            or is_stop_requested(thread_id)
            or is_mutating(thread_id)
            or self._job_active(thread_id) is not None
        )

    def _require_idle(self, thread_id: str) -> None:
        job = self._job_active(thread_id)
        if job is not None:
            raise RunBusy("这一轮已有待执行的推进任务，请等待完成后再操作")

    def start_failure_message(self, thread_id: str) -> str | None:
        job = self.runtime_store().last_job(thread_id)
        if job is None or job.kind != "start" or job.state != "failed":
            return None
        try:
            self.status(thread_id)
        except HitlError:
            return job.error or "启动失败"
        return None

    def mark_interrupted_after_crash(self, thread_id: str) -> None:
        try:
            st = self.status(thread_id)
            if st.phase == "interrupted" and not st.values.get("run_interrupted"):
                self._locked_mark_interrupted(thread_id)
        except (HitlError, RunBusy):
            return
        self._index(thread_id)

    def _bound(self, thread_id: str) -> CompiledStateGraph:
        """未选流程时用默认图。选定流程的轮次用那张编译图。"""
        with self._graphs_lock:
            found = self._graphs.get(thread_id)
            if found is not None:
                self._graphs.move_to_end(thread_id)
                return found
        snap = self._graph.get_state(self._config(thread_id))
        workflow_id = str((snap.values or {}).get("workflow_id") or "").strip()
        if not workflow_id:
            return self._graph
        definition = workflow_definition_of(snap.values or {})
        if definition is None:
            # 允许历史记录查询、停止和删除；恢复前另外检查定义快照。
            return self._graph
        from geni_studio.workflows.executable import compile_workflow

        compiled = compile_workflow(definition, checkpointer=self._graph.checkpointer)
        self._remember_graph(thread_id, compiled)
        return compiled

    def _remember_graph(self, thread_id: str, compiled: CompiledStateGraph) -> None:
        with self._graphs_lock:
            self._graphs[thread_id] = compiled
            self._graphs.move_to_end(thread_id)
            while len(self._graphs) > _GRAPH_CACHE_SIZE:
                self._graphs.popitem(last=False)

    def _require_resume_definition(self, thread_id: str) -> None:
        values = self._graph.get_state(self._config(thread_id)).values or {}
        if values.get("workflow_id") and workflow_definition_of(values) is None:
            raise HitlError("历史 Run 缺少流程定义快照，无法安全续跑，请新建一轮")

    @staticmethod
    def new_thread_id() -> str:
        return str(uuid.uuid4())

    def role_defaults(self, *, project_id: str = "", thread_id: str = "") -> dict[str, Any]:
        """供模型表单解释继承值；仅返回后端、模型和推理设置，不暴露配置全文。"""
        import os

        from geni_studio.backends.base import factory_default_model
        from geni_studio.backends.codex_settings import (
            factory_reasoning_effort,
            normalize_reasoning_effort,
        )
        from geni_studio.backends.reasoning import normalize_effort
        from geni_studio.config.context import build_run_context, factory_root

        if thread_id:
            values = self.status(thread_id).values
            effective = values.get("config_snapshot_effective") or {}
        else:
            effective = dict(build_run_context(project_id=project_id).merged)
            effective["_backend"] = os.environ.get("GENI_STUDIO_BACKEND", "").strip().lower() or "cursor"
            effective["_models"] = {mode: factory_default_model(mode) for mode in ("cursor", "codex", "stub")}
            effective["_codex_reasoning_effort"] = factory_reasoning_effort()
        configs = effective.get("backends") or {}
        names = set(configs) | set(effective.get("_roles") or {})
        names |= {path.parent.name for path in (factory_root() / "roles").glob("*/role.md")}
        roles = {}
        for name in names:
            config = configs.get(name) or {}
            backend = str(config.get("backend") or effective.get("_backend") or "").strip().lower()
            model = str(config.get("model") or (effective.get("_models") or {}).get(backend) or "").strip()
            effort = config.get("reasoning_effort")
            if effort is None and backend == "codex":
                effort = effective.get("_codex_reasoning_effort")
            roles[name] = {
                "backend": backend,
                "model": "" if model.lower() in {"auto", "default"} else model,
                "reasoning_effort": (
                    normalize_reasoning_effort(effort) if backend == "codex"
                    else normalize_effort(effort) if backend == "cursor" else ""
                ),
            }
        return {"roles": roles}

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
                from geni_studio.workspace.policy import WriteBusy

                if not isinstance(exc, (RunPaused, RunStopped, WriteBusy)) and not is_stop_requested(thread_id):
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
        lock = None
        if path:
            from geni_studio.workspace.layout import workspace_lock

            lock = workspace_lock(path)
        from geni_studio.workspace.policy import exclusive_write

        write_lock = (
            exclusive_write(lock[0], owner=thread_id, wait_seconds=_WRITE_LOCK_WAIT_SECONDS, lock_file=lock[1])
            if lock is not None
            else nullcontext()
        )
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
        from geni_studio.backends.reasoning import use_role_reasoning_efforts
        from geni_studio.backends.runtime import use_config

        state = payload if payload is not None else self.status(thread_id).values
        try:
            with (
                write_lock, ctx, use_config(state.get("config_snapshot_effective")),
                use_role_reasoning_efforts(state.get("role_reasoning_efforts")),
            ):
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
        self._index(thread_id, st)
        self.notify_change(thread_id)
        if workspace_enabled():
            run_dir = _run_dir_for(st.values, thread_id)
            if run_dir is not None:
                persist_values(
                    run_dir=run_dir,
                    thread_id=thread_id,
                    phase=st.phase,
                    values=st.values,
                )
            workspace = str(st.values.get("workspace_path") or "")
            if st.phase in ("completed", "rejected", "stopped") and st.values.get("base_branch") and workspace:
                from geni_studio.workspace.push_guard import release

                release(Path(workspace), thread_id)
        return st

    @staticmethod
    def _infer_awaiting(
        next_nodes: tuple[str, ...],
        values: dict[str, Any],
        created_at: str = "",
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
            since = (
                str(values.get("awaiting_since") or "").strip()
                or str(created_at or "").strip()
                or datetime.now(UTC).isoformat()
            )
            summary = presenter.workflow_gate_summary(values, head) or gate_summary(head)
            note = str(values.get("gate_timeout_note") or "").strip() or presenter.timeout_note(since)
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
        """只读。没有执行体的运行中轮次视为中断；有待执行任务的轮次视为运行中。"""
        cfg = self._config(thread_id)
        snap = self._bound(thread_id).get_state(cfg)
        if not snap.values and not snap.next:
            raise RunNotFound(f"未知 thread_id={thread_id!r}")
        next_nodes = tuple(snap.next or ())
        values = dict(snap.values or {})
        awaiting = self._infer_awaiting(next_nodes, values, str(getattr(snap, "created_at", "") or ""))
        phase = self._phase(next_nodes, values, awaiting)
        if phase == "running" and not self._is_active(thread_id):
            phase = "interrupted"
            values.setdefault("interrupted_at", next_nodes[0] if next_nodes else "")
        elif phase in ("awaiting_human", "interrupted", "paused") and self._job_active(thread_id) is not None:
            phase = "running"
            awaiting = None
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
        role_reasoning_efforts: dict[str, str] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        from geni_studio.backends.reasoning import clean_role_reasoning_efforts
        from geni_studio.config.context import build_run_context, factory_root
        from geni_studio.config.precheck import precheck_scenario_materials
        from geni_studio.config.snapshot import capture_config_snapshot
        from geni_studio.hitl.run_name import assign_run_name

        efforts = clean_role_reasoning_efforts(role_reasoning_efforts)
        precheck_scenario_materials(scenario_key, project_id)
        tid = thread_id or self.new_thread_id()
        taken = self.taken_run_names(project_id)
        snap = capture_config_snapshot(scenario_key, project_id)
        ctx = build_run_context(
            scenario_key=snap["scenario_key"] or scenario_key,
            project_id=snap["project_id"] or project_id,
        )
        import os
        from copy import deepcopy

        from geni_studio.backends.base import factory_default_model
        from geni_studio.backends.codex_settings import factory_reasoning_effort

        effective = deepcopy(ctx.merged)
        effective["_backend"] = os.environ.get("GENI_STUDIO_BACKEND", "").strip().lower() or "cursor"
        effective["_models"] = {name: factory_default_model(name) for name in ("cursor", "codex", "stub")}
        effective["_codex_reasoning_effort"] = factory_reasoning_effort()
        configured = (ctx.merged.get("verification") or {}).get("command") or ""
        if isinstance(configured, list):
            import shlex

            configured = shlex.join(str(item) for item in configured)
        effective["_test_command"] = str(os.environ.get("GENI_STUDIO_TEST_COMMAND") or configured)
        from geni_studio.runtime.snapshots import put

        effective["_roles_ref"] = put(
            {
                path.parent.name: path.read_text(encoding="utf-8")
                for path in sorted((factory_root() / "roles").glob("*/role.md"))
            }
        )
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
            workflow_exists,
        )

        root = factory_root()
        direct_branch = uses_current_branch(profile, root)
        if profile and workflow_exists(profile, root):
            from geni_studio.workflows.executable import compile_for_project

            compiled, extra = compile_for_project(
                profile,
                checkpointer=self._graph.checkpointer,
                root=root,
            )
            self._remember_graph(tid, compiled)
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
        initial["role_reasoning_efforts"] = efforts
        if attachment_ids:
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
        role_reasoning_efforts: dict[str, str] | None = None,
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
            role_reasoning_efforts=role_reasoning_efforts,
        )
        from geni_studio.workspace.layout import workspace_lock
        from geni_studio.workspace.policy import assert_write_available

        lock = workspace_lock(str(initial.get("workspace_path") or ""))
        if lock is not None:
            assert_write_available(lock[0], lock[1])
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
        role_reasoning_efforts: dict[str, str] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """准备本轮并入队启动任务，HTTP 可立即返回 thread_id。"""
        tid, initial = self._prepare_start(
            human_request=human_request,
            scenario_key=scenario_key,
            project_id=project_id,
            thread_id=thread_id,
            run_name=run_name,
            node_tools=node_tools,
            attachment_ids=attachment_ids,
            role_models=role_models,
            role_reasoning_efforts=role_reasoning_efforts,
        )
        from geni_studio.workspace.layout import workspace_lock
        from geni_studio.workspace.policy import assert_write_available

        path = str(initial.get("workspace_path") or "")
        lock = workspace_lock(path)
        if lock is not None:
            assert_write_available(lock[0], lock[1])
        self.runtime_store().upsert_index(
            tid,
            project_id=str(initial.get("project_id") or ""),
            run_name=str(initial.get("run_name") or tid),
            phase="running",
            current="",
        )
        self._dispatch(tid, "start", initial)
        return tid, initial

    def view(self, thread_id: str) -> dict[str, Any]:
        """状态接口：已有检查点时给完整状态；启动任务尚未写检查点时给一帧运行中状态。"""
        try:
            return self.status_dict(thread_id)
        except HitlError:
            job = self._job_active(thread_id)
            if job is not None and job.kind == "start" and isinstance(job.payload, dict):
                return self.provisional_status_dict(thread_id, job.payload)
            raise

    def provisional_status_dict(self, thread_id: str, initial: dict[str, Any]) -> dict[str, Any]:
        """检查点尚未写入时，给前端一帧运行中状态。"""
        st = RunStatus(
            thread_id=thread_id,
            phase="running",
            next_nodes=("project_manager_draft",),
            awaiting_human=None,
            values=dict(initial),
        )
        return {
            **presenter.status_payload(st, st.values),
            "stop_requested": False,
            "pause_requested": False,
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
    def set_role_models(
        self, thread_id: str, role_models: dict[str, str],
        role_reasoning_efforts: dict[str, str] | None = None,
    ) -> RunStatus:
        """保存本轮角色模型和可选的推理覆盖；省略推理映射时保留原值。"""
        st = self.status(thread_id)
        if st.phase in ("completed", "rejected", "stopped"):
            raise HitlError("这一轮已经结束。")
        from geni_studio.backends.reasoning import clean_role_reasoning_efforts

        update = {"role_models": role_models}
        if role_reasoning_efforts is not None:
            update["role_reasoning_efforts"] = clean_role_reasoning_efforts(role_reasoning_efforts)
        self._bound(thread_id).update_state(self._config(thread_id), update)
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
        actor: str = "",
    ) -> RunStatus:
        """写入人的决定并在当前线程推进到下一个停点（命令行与测试使用）。"""
        advance = self._apply_hitl(
            thread_id,
            gate_decision=gate_decision,
            human_reply=human_reply,
            channel=channel,
            escalation_choice=escalation_choice,
            actor=actor,
        )
        if advance:
            self._invoke(thread_id, None)
        return self._done(thread_id)

    def request_hitl(
        self,
        thread_id: str,
        *,
        gate_decision: Literal["approved", "rejected"] | None = None,
        human_reply: str = "",
        channel: str = "web",
        escalation_choice: EscalationChoice | None = None,
        actor: str = "",
    ) -> RunStatus:
        """写入人的决定并入队推进任务，立即返回（Web 与飞书使用）。"""
        job = self._apply_hitl_and_enqueue(
            thread_id,
            gate_decision=gate_decision,
            human_reply=human_reply,
            channel=channel,
            escalation_choice=escalation_choice,
            actor=actor,
        )
        self._kick(job)
        return self.status(thread_id)

    @run_mutation
    def _apply_hitl_and_enqueue(self, thread_id: str, **kwargs: Any):
        self._require_idle(thread_id)
        advance = self._apply_hitl(thread_id, **kwargs)
        self._index(thread_id)
        return self._enqueue(thread_id, "invoke") if advance else None

    def _apply_hitl(
        self,
        thread_id: str,
        *,
        gate_decision: Literal["approved", "rejected"] | None = None,
        human_reply: str = "",
        channel: str = "web",
        escalation_choice: EscalationChoice | None = None,
        actor: str = "",
    ) -> bool:
        """写入人的决定；返回是否需要继续推进图。"""
        st = self.status(thread_id)
        if st.phase != "awaiting_human" or st.awaiting_human is None:
            raise NotAwaiting("当前 Run 不在 awaiting_human，无法提交 HITL")
        self._require_resume_definition(thread_id)
        if channel == "feishu":
            _check_feishu_approver(str(st.values.get("project_id") or ""), actor)
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
            actor=actor,
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
            _note_answer(thread_id, st, human_reply, gate_decision, channel, actor)
            return True

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
            _note_answer(thread_id, st, human_reply, "replied", channel, actor)
            snap = self._bound(thread_id).get_state(cfg)
            if not snap.next:
                self._bound(thread_id).update_state(cfg, None, as_node="tester_testability")
            # 澄清答复只解决提问，不等同于批准当前或即将进入的关卡。
            snap = self._bound(thread_id).get_state(cfg)
            gates = set(GATE_NODES) | set(snap.values.get("workflow_gates") or [])
            return not any(node in gates for node in snap.next)

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
            _note_answer(thread_id, st, human_reply, str(choice), channel, actor)
            if choice == "continue":
                snap = self._bound(thread_id).get_state(cfg)
                if not snap.next:
                    resume_at = str(st.values.get("escalated_from") or "developer")
                    if resume_at not in self._bound(thread_id).nodes:
                        resume_at = "developer"
                    self._bound(thread_id).update_state(cfg, None, as_node=resume_at)
                    snap = self._bound(thread_id).get_state(cfg)
                # 继续后若停在关卡前，等待人的决定，不直接执行关卡。
                gates = set(GATE_NODES) | set(snap.values.get("workflow_gates") or [])
                return not any(node in gates for node in snap.next)
            return False

        raise HitlError(f"未知 kind={awaiting.kind!r}")

    def submit_from_feishu_card(
        self,
        *,
        thread_id: str,
        gate_decision: Literal["approved", "rejected"] | None = None,
        human_reply: str = "",
        escalation_choice: EscalationChoice | None = None,
        actor: str = "",
    ) -> RunStatus:
        """飞书卡片回调：写入决定后入队推进，立即返回。"""
        if escalation_choice is not None:
            return self.request_hitl(
                thread_id,
                human_reply=human_reply,
                escalation_choice=escalation_choice,
                channel="feishu",
                actor=actor,
            )
        if gate_decision not in ("approved", "rejected"):
            raise HitlError("gate 卡片回调缺少 gate_decision")
        return self.request_hitl(
            thread_id,
            gate_decision=gate_decision,
            human_reply=human_reply,
            channel="feishu",
            actor=actor,
        )

    def stop(self, thread_id: str, *, channel: str = "web", actor: str = "") -> RunStatus:
        from geni_studio.hitl.control import (
            cancel_active_runs,
            clear_stop_request,
            request_stop,
        )

        store = self.runtime_store()
        job = store.active_job(thread_id)
        store.set_control(thread_id, stop=True)
        busy = request_stop(thread_id)
        cancel_active_runs(thread_id)
        if job is not None and job.state == "queued":
            store.finish(job.id, error="本轮已停止")
            if job.kind == "start" and isinstance(job.payload, dict):
                try:
                    self.status(thread_id)
                except HitlError:
                    self._seed_stopped_locked(thread_id, job.payload)
                    store.set_control(thread_id, stop=False, pause=False)
                    self._index(thread_id)
                    return self.status(thread_id)
            job = None
        if busy or job is not None:
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
            store.set_control(thread_id, stop=False)
            raise HitlError(f"Run 已结束（phase={st.phase}），无法停止")
        if st.phase == "stopped":
            clear_stop_request(thread_id)
            store.set_control(thread_id, stop=False)
            return st
        return self._finish_stop(thread_id, channel=channel, actor=actor)

    @run_mutation
    def _seed_stopped_locked(self, thread_id: str, payload: dict[str, Any]) -> None:
        self._seed_stopped(thread_id, payload)

    def pause(self, thread_id: str) -> RunStatus:
        """暂停本轮。不结束检查点，已完成的节点保持完成。"""
        from geni_studio.hitl.control import request_pause

        st = self.status(thread_id)
        if st.phase == "paused":
            return st
        if st.phase != "running":
            raise HitlError(f"当前阶段是{st.phase}，不能暂停")
        store = self.runtime_store()
        store.set_control(thread_id, pause=True)
        busy = request_pause(thread_id)
        if busy or store.active_job(thread_id) is not None:
            return self.status(thread_id)
        return self._finish_pause(thread_id)

    @run_mutation
    def resume(self, thread_id: str) -> RunStatus:
        """从暂停的节点继续，不重做已完成节点。"""
        self._prepare_resume(thread_id)
        self._invoke(thread_id, None)
        return self._done(thread_id)

    def request_resume(self, thread_id: str) -> RunStatus:
        self._kick(self._prepare_resume_and_enqueue(thread_id))
        return self.status(thread_id)

    @run_mutation
    def _prepare_resume_and_enqueue(self, thread_id: str):
        self._require_idle(thread_id)
        self._prepare_resume(thread_id)
        return self._enqueue(thread_id, "invoke")

    def _prepare_resume(self, thread_id: str) -> None:
        from geni_studio.hitl.control import clear_pause_request

        st = self.status(thread_id)
        if st.phase != "paused":
            raise HitlError(f"当前阶段是{st.phase}，不能继续")
        self._require_resume_definition(thread_id)
        clear_pause_request(thread_id)
        self.runtime_store().set_control(thread_id, pause=False)
        self._bound(thread_id).update_state(
            self._config(thread_id),
            {"run_paused": False, "paused_at": ""},
        )

    @run_mutation
    def continue_interrupted(self, thread_id: str) -> RunStatus:
        """从中断的节点接着做，不重做已完成的节点。"""
        self._prepare_continue(thread_id)
        self._invoke(thread_id, None)
        return self._done(thread_id)

    def request_continue(self, thread_id: str) -> RunStatus:
        self._kick(self._prepare_continue_and_enqueue(thread_id))
        return self.status(thread_id)

    @run_mutation
    def _prepare_continue_and_enqueue(self, thread_id: str):
        self._require_idle(thread_id)
        self._prepare_continue(thread_id)
        return self._enqueue(thread_id, "invoke")

    def _prepare_continue(self, thread_id: str) -> None:
        st = self.status(thread_id)
        if st.phase != "interrupted":
            raise HitlError(f"当前阶段是{st.phase}，不能续跑")
        self._require_resume_definition(thread_id)
        self._bound(thread_id).update_state(
            self._config(thread_id),
            {"run_interrupted": False, "interrupted_at": ""},
        )

    @run_mutation
    def _locked_mark_interrupted(self, thread_id: str) -> None:
        self._mark_interrupted(thread_id)

    def _index(self, thread_id: str, st: RunStatus | None = None) -> None:
        try:
            st = st or self.status(thread_id)
        except HitlError:
            return
        self.runtime_store().upsert_index(
            thread_id,
            project_id=str(st.values.get("project_id") or ""),
            run_name=str(st.values.get("run_name") or thread_id),
            phase=st.phase,
            current=str(presenter.rail_for(st).get("current") or ""),
        )

    def taken_run_names(self, project_id: str) -> set[str]:
        self._ensure_index()
        return self.runtime_store().taken_names(project_id)

    def _ensure_index(self) -> None:
        """首次使用运行索引时，从检查点回填一次。"""
        store = self.runtime_store()
        if store.meta("index_backfilled"):
            return
        for thread_id, _values in latest_run_records(self._graph):
            self._index(thread_id)
        store.set_meta("index_backfilled", datetime.now(UTC).isoformat())

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
        paused_at = st.next_nodes[0] if st.next_nodes else str(presenter.rail_for(st).get("current") or "")
        self._bound(thread_id).update_state(
            self._config(thread_id),
            {"run_paused": True, "paused_at": paused_at},
        )
        clear_pause_request(thread_id)
        self.runtime_store().set_control(thread_id, pause=False)
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

    def _finish_stop(self, thread_id: str, *, channel: str = "web", actor: str = "") -> RunStatus:
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
        stopped_at = str(presenter.rail_for(st).get("current") or "")
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
                actor=actor,
            ),
        }
        cfg = self._config(thread_id)
        self._bound(thread_id).update_state(cfg, patch, as_node=as_node)
        self._bound(thread_id).update_state(cfg, None, as_node=END)
        clear_stop_request(thread_id)
        clear_pause_request(thread_id)
        self.runtime_store().set_control(thread_id, stop=False, pause=False)
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
                    "role_reasoning_efforts": dict(draft.get("role_reasoning_efforts") or {}),
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
            "role_reasoning_efforts": dict(values.get("role_reasoning_efforts") or {}),
            "attachments": [],
        }

    def list_runs(self, *, project_id: str = "", phase: str = "") -> list[dict[str, Any]]:
        """按运行索引列出已有轮次；阶段按当前执行情况校正。"""
        self._ensure_index()
        rows: list[dict[str, Any]] = []
        want_phase = phase.strip()
        for row in self.runtime_store().index_rows(project_id=project_id.strip()):
            current_phase = row.phase
            if current_phase in ("running", "awaiting_human", "paused", "interrupted"):
                try:
                    current_phase = self.status(row.thread_id).phase
                except HitlError:
                    if self._job_active(row.thread_id) is None:
                        continue
                    current_phase = "running"
            if want_phase and current_phase != want_phase:
                continue
            rows.append(
                {
                    "thread_id": row.thread_id,
                    "run_name": row.run_name or row.thread_id,
                    "phase": current_phase,
                    "project_id": row.project_id,
                    "current": row.current,
                }
            )
        return rows

    @run_mutation
    def delete_run(self, thread_id: str, *, confirm_name: str) -> list[str]:
        """删除一轮检查点并回收工作树与运行目录。名称必须一致，运行中的一轮要先停止。"""
        from geni_studio.hitl.control import clear_pause_request, clear_stop_request

        st = self.status(thread_id)
        if st.phase == "running":
            raise HitlError("这一轮还在运行，先停止再删除。")
        expected = str(st.values.get("run_name") or thread_id).strip() or thread_id
        if confirm_name.strip() != expected:
            raise RunConflict("名称不一致，没有删除。")
        saver = getattr(self._graph, "checkpointer", None)
        if saver is None or not hasattr(saver, "delete_thread"):
            raise HitlError("当前检查点不能删除这一轮。")
        saver.delete_thread(thread_id)
        with self._graphs_lock:
            self._graphs.pop(thread_id, None)
        self.runtime_store().forget_thread(thread_id)
        self.notify_change(thread_id)
        clear_stop_request(thread_id)
        clear_pause_request(thread_id)
        from geni_studio.workspace.gc import remove_run_workspace

        return remove_run_workspace(str(st.values.get("workspace_path") or ""), thread_id).lines()

    def live_thread_ids(self) -> set[str]:
        self._ensure_index()
        return {row.thread_id for row in self.runtime_store().index_rows()}

    @observation_mutation
    def note_gate_timeout(self, thread_id: str) -> RunStatus:
        """等待超过时限时在审计中记一笔未批复，关卡仍停在原地；由后台巡检调用。"""
        st = self.status(thread_id)
        ah = st.awaiting_human
        if ah is None or ah.kind != "gate" or st.values.get("gate_timeout_recorded"):
            return st
        note = presenter.timeout_note(ah.since)
        if not note:
            return st
        audit = str(st.values.get("hitl_audit_log") or "").strip()
        line = f"[timeout] {note}"
        if line not in audit:
            audit = f"{audit}\n{line}".strip()
        self._bound(thread_id).update_state(
            self._config(thread_id),
            {
                "awaiting_since": ah.since,
                "gate_timeout_recorded": True,
                "gate_timeout_note": note,
                "hitl_audit_log": audit,
            },
        )
        return self.status(thread_id)

    def sweep(self) -> None:
        """后台巡检：写入关卡超时审计，把没有执行体的运行中轮次持久化为中断，刷新索引。"""
        self._ensure_index()
        for row in self.runtime_store().index_rows():
            if row.phase in ("completed", "rejected", "stopped"):
                continue
            try:
                st = self.status(row.thread_id)
            except HitlError:
                continue
            if st.awaiting_human is not None and st.awaiting_human.kind == "gate":
                st = self.note_gate_timeout(row.thread_id)
            elif st.phase == "interrupted" and not st.values.get("run_interrupted"):
                try:
                    self._locked_mark_interrupted(row.thread_id)
                except RunBusy:
                    continue
            self._index(row.thread_id)
        self.runtime_store().prune_jobs()

    def status_dict(self, thread_id: str) -> dict[str, Any]:
        """只读：不写检查点。"""
        st = self.status(thread_id)
        ah = st.awaiting_human
        values = dict(st.values)
        if ah is not None and ah.kind == "gate":
            values.setdefault("awaiting_since", ah.since)
            note = str(values.get("gate_timeout_note") or "") or presenter.timeout_note(ah.since)
            if note:
                values["gate_timeout_note"] = note
                values["gate_timeout_recorded"] = True
        job = self._job_active(thread_id)
        stop_flag, pause_flag = self.runtime_store().controls(thread_id)
        return {
            **presenter.status_payload(st, values),
            "stop_requested": _stop_requested(st.thread_id) or stop_flag,
            "pause_requested": _pause_requested(st.thread_id) or pause_flag,
            "job": {"state": job.state, "note": job.note} if job is not None else None,
        }


def _stop_requested(thread_id: str) -> bool:
    from geni_studio.hitl.control import is_stop_requested

    return is_stop_requested(thread_id)


def _pause_requested(thread_id: str) -> bool:
    from geni_studio.hitl.control import is_pause_requested

    return is_pause_requested(thread_id)


def workflow_definition_of(values: dict[str, Any]) -> dict[str, Any] | None:
    """运行使用的流程定义：新运行按快照引用读取，旧运行读内联字段。"""
    from geni_studio.runtime.snapshots import SnapshotMissing, get

    ref = values.get("workflow_definition_ref")
    if ref:
        try:
            found = get(str(ref))
        except SnapshotMissing:
            return None
        return found if isinstance(found, dict) else None
    inline = values.get("workflow_definition")
    return inline if isinstance(inline, dict) else None


def _check_feishu_approver(project_id: str, actor: str) -> None:
    from geni_studio.hitl.feishu_config import feishu_approvers

    approvers = feishu_approvers(project_id)
    if approvers and actor not in approvers:
        raise HitlError(f"飞书用户 {actor or '（未知）'} 不在本项目的审批人名单中，未记录这次批复。")


def _notice_key(thread_id: str) -> str:
    return f"feishu_notice:{thread_id}"


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


def _note_answer(
    thread_id: str, st: RunStatus, reply: str, decision: str, channel: str, actor: str
) -> None:
    """把人的答复写回提出选项的那次会话，供运行页按轮展示；写失败不影响批复本身。"""
    from geni_studio.hitl.conversation import record_human_answer

    _, _, groups = presenter.reading_and_choices(st.awaiting_human, st.values)
    try:
        record_human_answer(
            thread_id,
            groups,
            reply=reply,
            decision=decision,
            channel=channel,
            actor=actor,
            workspace_path=str(st.values.get("workspace_path") or ""),
        )
    except OSError:
        pass
