"""把项目选定的流程编译成当轮 LangGraph。"""

from __future__ import annotations

import re
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from auto_studio.config.context import ConfigError
from auto_studio.config.workflow_defs import get_workflow
from auto_studio.roles.loader import role_contract
from auto_studio.workflows.default import (
    FactoryState,
    _with_stop_guard,
    max_dev_retries_for_state,
)

_STATUS_FAIL = re.compile(r"(?m)^STATUS:\s*fail\s*$")
DECISIONS = {"approve": "批准或驳回"}
_ESCALATE = "workflow_escalate"


def resolve_executable(workflow: dict[str, Any], *, root: Any = None) -> dict[str, Any]:
    """补上活动的产物契约，并拒绝缺少决定类型的决策点。"""
    allowed = set(FactoryState.__annotations__)
    errors: list[str] = []
    nodes: list[dict[str, Any]] = []
    for raw in workflow.get("nodes") or []:
        node = dict(raw)
        kind = node.get("kind")
        name = str(node.get("name") or node.get("id") or "")
        if kind == "activity":
            inputs, outputs, problems = _activity_contract(node, root)
            errors.extend(problems)
            unknown = [item for item in [*inputs, *outputs] if item not in allowed]
            if unknown:
                errors.append(f"活动「{name}」使用了图状态里没有的产物：{'、'.join(unknown)}。")
            if not outputs and "outputs" not in node:
                errors.append(f"活动「{name}」缺少产出产物。")
            node["inputs"] = inputs
            node["outputs"] = outputs
        elif kind == "gate":
            decision = str(node.get("decision") or "").strip()
            if decision not in DECISIONS:
                errors.append(f"决策点「{name}」缺少决定类型。")
            node["decision"] = decision
        if node.get("id") == _ESCALATE:
            errors.append("节点标识 workflow_escalate 已留给回退升级。")
        nodes.append(node)
    runnable = [node for node in nodes if node.get("kind") in {"activity", "gate"}]
    if not runnable:
        errors.append("流程里没有可执行的活动或决策点。")
    if errors:
        raise ConfigError("\n".join(errors))
    prepared = dict(workflow)
    prepared["nodes"] = nodes
    return prepared


def compile_for_project(
    workflow_id: str,
    *,
    checkpointer: BaseCheckpointSaver,
    root: Any = None,
) -> tuple[Any, dict[str, Any]]:
    """编译已保存的流程，并给出写入运行状态的节点清单。"""
    from auto_studio.config.context import factory_root

    root = root or factory_root()
    loaded = get_workflow(workflow_id, root=root)
    prepared = resolve_executable(loaded["workflow"], root=root)
    compiled = compile_workflow(prepared, checkpointer=checkpointer)
    return compiled, run_state(prepared)


def compile_workflow(workflow: dict[str, Any], *, checkpointer: BaseCheckpointSaver) -> Any:
    nodes = list(workflow["nodes"])
    executable = [node for node in nodes if node["kind"] in {"activity", "gate"}]
    by_id = {node["id"]: node for node in nodes}
    builder = StateGraph(FactoryState)
    for node in executable:
        if node["kind"] == "activity":
            fn = _activity(node)
        else:
            fn = _gate(node)
        builder.add_node(node["id"], _with_stop_guard(fn))
    builder.add_node(_ESCALATE, _with_stop_guard(_escalate))
    builder.add_edge(START, executable[0]["id"])
    for index, node in enumerate(executable):
        nxt = executable[index + 1]["id"] if index + 1 < len(executable) else END
        returns = str(node.get("returns_to") or "")
        if returns:
            node["graph_return"] = _graph_target(returns, nodes, executable)
        if node["kind"] == "gate":
            builder.add_conditional_edges(
                node["id"],
                _gate_route(nxt),
                {_edge_key(nxt): nxt, "__end__": END},
            )
        elif returns:
            target = _graph_target(returns, nodes, executable)
            paths = {_edge_key(nxt): nxt, target: _node_or_end(target, by_id, executable), _ESCALATE: _ESCALATE}
            builder.add_conditional_edges(node["id"], _return_route(nxt), paths)
        elif nxt is END:
            builder.add_edge(node["id"], END)
        else:
            builder.add_edge(node["id"], nxt)
    builder.add_edge(_ESCALATE, END)
    gates = [node["id"] for node in executable if node["kind"] == "gate"]
    return builder.compile(checkpointer=checkpointer, interrupt_before=gates)


def run_state(workflow: dict[str, Any]) -> dict[str, Any]:
    meta: list[dict[str, Any]] = []
    for node in workflow["nodes"]:
        outputs = node.get("outputs") or []
        meta.append(
            {
                "id": node["id"],
                "label": node["name"],
                "role": node["role"],
                "kind": node["kind"],
                "artifacts": list(outputs) if node["kind"] == "activity" else [],
            }
        )
    return {
        "workflow_id": workflow["workflow_id"],
        "workflow_gates": [node["id"] for node in workflow["nodes"] if node["kind"] == "gate"],
        "workflow_nodes": meta,
    }


def _explicit_outputs(value: object) -> list[dict[str, str]]:
    from auto_studio.config.workflow_defs import _output_items

    return _output_items(value)


def _template_problem(activity: str, item: dict[str, str]) -> list[str]:
    from auto_studio.config.registry import template_file_error

    label = f"活动「{activity}」的输出「{item['name']}」"
    template = item.get("template") or ""
    if not template:
        return [f"{label}没有模板。"]
    if item.get("source") == "link":
        if not template.startswith(("http://", "https://")):
            return [f"{label}的链接必须是 http 或 https。"]
        return []
    message = template_file_error(template)
    if message:
        return [f"{label}的本地文件不可用：{message}"]
    return []


def _activity_contract(node: dict[str, Any], root: Any) -> tuple[list[str], list[str], list[str]]:
    role = str(node.get("role") or "")
    name = str(node.get("name") or role)
    try:
        defaults_in, defaults_out = role_contract(role, root)
    except FileNotFoundError as exc:
        raise ConfigError(f"活动「{name}」的角色不存在。") from exc
    if "inputs" in node:
        inputs = [str(item).strip() for item in (node.get("inputs") or []) if str(item).strip()]
    else:
        inputs = list(defaults_in)
    problems: list[str] = []
    seen_inputs: set[str] = set()
    for item in inputs:
        if item in seen_inputs:
            problems.append(f"活动「{name}」的产物名「{item}」重复。")
        seen_inputs.add(item)
    if "outputs" in node:
        items = _explicit_outputs(node.get("outputs"))
        if not items:
            problems.append(f"活动「{name}」还没有输出。")
        seen_in = set(inputs)
        seen_out: set[str] = set()
        for item in items:
            output_name = item["name"]
            if output_name in seen_out or output_name in seen_in:
                problems.append(f"活动「{name}」的产物名「{output_name}」重复。")
            seen_out.add(output_name)
            problems.extend(_template_problem(name, item))
        outputs = [item["name"] for item in items]
        node["output_specs"] = items
    else:
        outputs = list(defaults_out)
    return inputs, outputs, problems


def _activity(node: dict[str, Any]):
    inputs = list(node.get("inputs") or [])
    outputs = list(node.get("outputs") or [])

    def fn(state: FactoryState) -> dict[str, Any]:
        from auto_studio.backends.runner import invoke_role

        sections = [f"活动：{node['name']}"]
        request = str(state.get("human_request") or "")
        if request and "human_request" not in inputs:
            sections.append(f"人类原始需求：\n{request}")
        for key in inputs:
            sections.append(f"{key}：\n{state.get(key) or ''}")
        for spec in node.get("output_specs") or []:
            sections.append(_template_section(spec))
        if node.get("returns_to"):
            sections.append("若这一活动未能通过，最后一行只写 STATUS: fail。通过则不要写这一行。")
        body = invoke_role(
            role_name=str(node["role"]),
            user_prompt="\n\n".join(sections),
            stub_note=str(node["name"]),
        )
        update: dict[str, Any] = {key: body for key in outputs}
        counts = dict(state.get("return_counts") or {})
        target = ""
        origin = ""
        if node.get("returns_to") and _STATUS_FAIL.search(body):
            counts[node["id"]] = int(counts.get(node["id"]) or 0) + 1
            if counts[node["id"]] >= max_dev_retries_for_state(state):
                target = "__escalate__"
                origin = node["id"]
            else:
                target = str(node.get("graph_return") or node["returns_to"])
        update["return_counts"] = counts
        update["return_target"] = target
        update["escalated_from"] = origin
        return update

    fn.__name__ = f"activity_{node['id']}"
    return fn


def _template_section(spec: dict[str, str]) -> str:
    name = spec.get("name") or "输出"
    template = spec.get("template") or ""
    if spec.get("source") == "link":
        return f"输出「{name}」请按这个模板链接的结构来写：{template}"
    from pathlib import Path

    try:
        text = Path(template).read_text(encoding="utf-8")[:12000]
    except OSError:
        text = ""
    if not text:
        return f"输出「{name}」的模板在：{template}"
    return f"输出「{name}」请按下面的模板写：\n{text}"


def _gate(node: dict[str, Any]):
    def fn(state: FactoryState) -> dict[str, Any]:
        from auto_studio.hitl.gate import apply_gate_node

        cleared = apply_gate_node(str(node["id"]), state)
        cleared["return_target"] = ""
        return cleared

    fn.__name__ = f"gate_{node['id']}"
    return fn


def _escalate(state: FactoryState) -> dict[str, Any]:
    from datetime import UTC, datetime

    origin = str(state.get("escalated_from") or "")
    summary = "回退次数已达上限，请选择：继续 / 暂停 / 终止。"
    return {
        "hitl_pending_kind": "escalation",
        "hitl_summary": summary,
        "hitl_questions": [],
        "hitl_pending_since": datetime.now(UTC).isoformat(),
        "escalated_from": origin,
        "return_target": "",
    }


def _gate_route(nxt: str):
    key = _edge_key(nxt)

    def route(state: FactoryState) -> str:
        if state.get("last_gate_decision") == "rejected":
            return "__end__"
        return key

    return route


def _return_route(nxt: str):
    key = _edge_key(nxt)

    def route(state: FactoryState) -> str:
        target = str(state.get("return_target") or "")
        if target == "__escalate__":
            return _ESCALATE
        if target:
            return target
        return key

    return route


def _edge_key(nxt: str) -> str:
    return "__end__" if nxt is END else nxt


def _node_or_end(target: str, by_id: dict[str, dict[str, Any]], executable: list[dict[str, Any]]) -> str:
    if target in {node["id"] for node in executable}:
        return target
    kind = (by_id.get(target) or {}).get("kind")
    if kind == "end":
        return END
    return target


def _graph_target(returns_to: str, nodes: list[dict[str, Any]], executable: list[dict[str, Any]]) -> str:
    matched = next((node for node in nodes if node["id"] == returns_to), None)
    if matched and matched["kind"] == "start":
        return executable[0]["id"]
    if matched and matched["kind"] == "end":
        return END
    return returns_to
