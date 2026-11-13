"""运行状态的展示层：轨道、阅读区、选项与对外公开字段。

只读取 `RunStatus` 与检查点值，不写检查点，也不依赖 `GraphRunService`。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from geni_studio.config.context import ConfigError, build_run_context_from_state
from geni_studio.hitl.choices import choice_groups_from_reading, choices_from_reading
from geni_studio.hitl.rail import build_rail
from geni_studio.hitl.reading import human_reading, human_review


def status_payload(st: Any, values: dict[str, Any]) -> dict[str, Any]:
    """状态接口中与展示相关的字段；控制位与任务信息由调用方补充。"""
    ah = st.awaiting_human
    reading, choices, choice_groups = reading_and_choices(ah, values)
    awaiting = (
        {
            "kind": ah.kind,
            "since": ah.since,
            "gate_id": ah.gate_id,
            "questions": ah.questions,
            "summary": ah.summary,
        }
        if ah
        else None
    )
    if awaiting and ah.kind == "gate":
        awaiting["reject_label"] = gate_reject_label(values, ah.gate_id or "")
        pick = gate_pick(values, ah.gate_id or "")
        if pick is not None:
            awaiting["pick_options"] = pick["branches"]
        checklist = gate_items(values, ah.gate_id or "")
        if checklist is not None:
            awaiting["items"] = checklist["items"]
            awaiting["pass_rule"] = checklist["pass_rule"]
    return {
        "thread_id": st.thread_id,
        "phase": st.phase,
        "next_nodes": list(st.next_nodes),
        "awaiting_human": awaiting,
        "values": public_values(values),
        "limits": {"max_dev_retries": dev_retry_limit(values)},
        "rail": rail_for(st),
        "reading": reading,
        "review": human_review(awaiting, values),
        "choices": choices,
        "choice_groups": choice_groups,
    }


def reading_and_choices(
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


def timeout_note(since: str) -> str:
    limit = gate_timeout_seconds()
    try:
        started = datetime.fromisoformat(str(since))
    except ValueError:
        return ""
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    if limit > 0 and (datetime.now(UTC) - started).total_seconds() < limit:
        return ""
    return "超时未批复。本轮仍停在关卡上，不自动批准或驳回。"


def gate_timeout_seconds() -> float:
    import os

    raw = os.environ.get("GENI_STUDIO_GATE_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return 24 * 60 * 60
    try:
        return float(raw)
    except ValueError:
        return 24 * 60 * 60


def dev_retry_limit(values: dict[str, Any]) -> int:
    from geni_studio.workflows.default import max_dev_retries_for_state

    return max_dev_retries_for_state(values)


def rail_for(st: Any) -> dict[str, Any]:
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
    catalog, meta = workflow_catalog(values)
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


def workflow_catalog(
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


def _workflow_gate(values: dict[str, Any], gate_id: str) -> tuple[str, str] | None:
    """流程里该决策点的显示名与不通过时前往的节点名；后者为空表示结束本轮。"""
    raw = values.get("workflow_nodes")
    if not isinstance(raw, list):
        return None
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
            return name, reject_name
    return None


def workflow_gate_summary(values: dict[str, Any], gate_id: str) -> str:
    found = _workflow_gate(values, gate_id)
    if found is None:
        return ""
    name, reject_name = found
    if reject_name:
        return f"{name}：请批准，或不通过并前往「{reject_name}」。"
    return f"{name}：请批准，或不通过以结束本轮。"


def gate_pick(values: dict[str, Any], gate_id: str) -> dict[str, Any] | None:
    """择一决策点所对照的并行与可选的各路；不是择一决策点时返回 None。"""
    for item in values.get("workflow_nodes") or []:
        if isinstance(item, dict) and str(item.get("id") or "") == gate_id and item.get("pick_from"):
            branches = [
                {"id": str(branch.get("id") or ""), "name": str(branch.get("name") or "")}
                for branch in item.get("pick_branches") or []
                if isinstance(branch, dict)
            ]
            return {"from": str(item["pick_from"]), "branches": branches}
    return None


def gate_items(values: dict[str, Any], gate_id: str) -> dict[str, Any] | None:
    """决策点的决策项与汇总规则，见 ADR 0032；没有决策项时返回 None。"""
    for item in values.get("workflow_nodes") or []:
        if isinstance(item, dict) and str(item.get("id") or "") == gate_id and item.get("items"):
            entries = [
                {
                    "id": str(entry.get("id") or ""),
                    "title": str(entry.get("title") or ""),
                    "hint": str(entry.get("hint") or ""),
                    "required": entry.get("required") is not False,
                }
                for entry in item["items"]
                if isinstance(entry, dict)
            ]
            return {"items": entries, "pass_rule": str(item.get("pass_rule") or "all")}
    return None


def gate_reject_label(values: dict[str, Any], gate_id: str) -> str:
    found = _workflow_gate(values, gate_id)
    return found[1] if found else ""


def public_values(values: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    extra = values.get("extra_artifacts")
    merged = {**(extra if isinstance(extra, dict) else {}), **values}
    for key, val in merged.items():
        if key in {"workflow_definition", "workflow_definition_ref", "config_snapshot_effective", "extra_artifacts"}:
            continue
        if val is None:
            continue
        if isinstance(val, str) and len(val) > 2000:
            out[key] = val[:2000] + "…"
        else:
            out[key] = val
    return out
