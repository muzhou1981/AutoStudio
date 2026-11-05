"""LangGraph Run 与 HITL 提交（Web / 飞书共用）。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from langgraph.graph.state import CompiledStateGraph

from auto_studio.hitl.constants import GATE_NODES, gate_summary
from auto_studio.hitl.hitl_audit import audit_patch
from auto_studio.hitl.pm_clarification import merge_clarification_reply

RunPhase = Literal["running", "awaiting_human", "completed", "rejected"]
HitlKind = Literal["gate", "pm_clarification", "escalation"]
EscalationChoice = Literal["continue", "pause", "abort"]


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


class GraphRunService:
    """对单一已编译图提供启动、查询与 HITL 续跑。"""

    def __init__(self, compiled_graph: CompiledStateGraph) -> None:
        self._graph = compiled_graph

    @staticmethod
    def new_thread_id() -> str:
        return str(uuid.uuid4())

    def _config(self, thread_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": thread_id}}

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
        if head in GATE_NODES:
            return AwaitingHuman(
                kind="gate",
                since=datetime.now(UTC).isoformat(),
                gate_id=head,
                summary=gate_summary(head),
            )
        return None

    @staticmethod
    def _phase(
        next_nodes: tuple[str, ...],
        values: dict[str, Any],
        awaiting: AwaitingHuman | None,
    ) -> RunPhase:
        if awaiting is not None:
            return "awaiting_human"
        if values.get("last_gate_decision") == "rejected" and not next_nodes:
            return "rejected"
        if not next_nodes:
            return "completed"
        return "running"

    def status(self, thread_id: str) -> RunStatus:
        cfg = self._config(thread_id)
        snap = self._graph.get_state(cfg)
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

    def start(
        self,
        *,
        human_request: str,
        scenario_key: str = "",
        project_id: str = "",
        thread_id: str | None = None,
    ) -> RunStatus:
        tid = thread_id or self.new_thread_id()
        cfg = self._config(tid)
        initial: dict[str, Any] = {
            "human_request": human_request,
            "scenario_key": scenario_key,
            "project_id": project_id,
        }
        self._graph.invoke(initial, cfg)
        return self.status(tid)

    def advance_until_blocked(self, thread_id: str) -> RunStatus:
        cfg = self._config(thread_id)
        while True:
            snap = self._graph.get_state(cfg)
            values = dict(snap.values or {})
            if values.get("hitl_pending_kind"):
                break
            next_nodes = tuple(snap.next or ())
            if not next_nodes:
                break
            if next_nodes[0] in GATE_NODES:
                break
            self._graph.invoke(None, cfg)
        return self.status(thread_id)

    def open_hitl(
        self,
        thread_id: str,
        *,
        kind: Literal["pm_clarification", "escalation"],
        questions: list[str] | None = None,
        summary: str = "",
    ) -> RunStatus:
        st = self.status(thread_id)
        if st.phase == "completed" or st.phase == "rejected":
            raise HitlError(f"Run 已结束（phase={st.phase}），无法打开 HITL")
        cfg = self._config(thread_id)
        patch: dict[str, Any] = {
            "hitl_pending_kind": kind,
            "hitl_questions": questions or [],
            "hitl_summary": summary,
            "hitl_pending_since": datetime.now(UTC).isoformat(),
        }
        self._graph.update_state(cfg, patch)
        return self.status(thread_id)

    def _clear_pending_patch(self) -> dict[str, Any]:
        return {
            "hitl_pending_kind": None,
            "hitl_questions": [],
            "hitl_summary": "",
            "hitl_pending_since": None,
        }

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
            self._graph.update_state(cfg, patch)
            self._graph.invoke(None, cfg)
            return self.status(thread_id)

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
            self._graph.update_state(cfg, patch)
            snap = self._graph.get_state(cfg)
            if not snap.next:
                self._graph.update_state(cfg, None, as_node="tester_testability")
            self._graph.invoke(None, cfg)
            return self.status(thread_id)

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
            self._graph.update_state(cfg, patch)
            if choice == "continue":
                snap = self._graph.get_state(cfg)
                if not snap.next:
                    self._graph.update_state(cfg, None, as_node="developer")
                self._graph.invoke(None, cfg)
            return self.status(thread_id)

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

    def status_dict(self, thread_id: str) -> dict[str, Any]:
        st = self.status(thread_id)
        ah = st.awaiting_human
        return {
            "thread_id": st.thread_id,
            "phase": st.phase,
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
        }


def _public_values(values: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, val in values.items():
        if val is None:
            continue
        if isinstance(val, str) and len(val) > 2000:
            out[key] = val[:2000] + "…"
        else:
            out[key] = val
    return out
