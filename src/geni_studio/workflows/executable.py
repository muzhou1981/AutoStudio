"""把项目选定的流程编译成当轮 LangGraph。"""

from __future__ import annotations

import re
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from geni_studio.config.context import ConfigError
from geni_studio.config.workflow_defs import get_workflow
from geni_studio.roles.loader import role_contract
from geni_studio.workflows.default import (
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
    runnable = [
        node for node in nodes if node.get("kind") in {"activity", "gate", "parallel", "subgraph"}
    ]
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
    from geni_studio.config.context import factory_root

    root = root or factory_root()
    loaded = get_workflow(workflow_id, root=root)
    prepared = resolve_executable(loaded["workflow"], root=root)
    flat = _prepare_flat(prepared, root)
    compiled = compile_workflow(flat, checkpointer=checkpointer)
    return compiled, run_state(flat)


def compile_workflow(workflow: dict[str, Any], *, checkpointer: BaseCheckpointSaver) -> Any:
    nodes = list(workflow["nodes"])
    executable = [node for node in nodes if node["kind"] not in {"start", "end"}]
    by_id = {node["id"]: node for node in nodes}
    builder = StateGraph(FactoryState)
    for step in _iter_steps(executable):
        if step["kind"] == "activity":
            fn = _activity(step)
        else:
            fn = _gate(step)
        builder.add_node(step["id"], _with_stop_guard(fn))
    for node in executable:
        if node["kind"] != "parallel":
            continue
        builder.add_node(node["fork_id"], _with_stop_guard(_noop))
        builder.add_node(node["join_id"], _with_stop_guard(_join(node)))
    builder.add_node(_ESCALATE, _with_stop_guard(_escalate))
    builder.add_edge(START, _entry(executable[0]))
    for index, node in enumerate(executable):
        nxt = _entry(executable[index + 1]) if index + 1 < len(executable) else END
        if node["kind"] == "parallel":
            for branch in node["branches"]:
                builder.add_edge(node["fork_id"], branch["steps"][0]["id"])
                _link_steps(builder, branch["steps"], node["join_id"], nodes, by_id, executable)
            builder.add_edge(node["join_id"], nxt)
        else:
            _link_one(builder, node, nxt, nodes, by_id, executable)
    builder.add_edge(_ESCALATE, END)
    gates = [step["id"] for step in _iter_steps(executable) if step["kind"] == "gate"]
    return builder.compile(checkpointer=checkpointer, interrupt_before=gates)


def run_state(workflow: dict[str, Any]) -> dict[str, Any]:
    visible: list[dict[str, Any]] = []
    for node in workflow["nodes"]:
        if node.get("kind") == "parallel":
            visible.extend(_iter_steps([node]))
        elif node.get("kind") != "subgraph":
            visible.append(node)
    meta: list[dict[str, Any]] = []
    for node in visible:
        outputs = node.get("outputs") or []
        meta.append(
            {
                "id": node["id"],
                "label": node.get("label") or node["name"],
                "role": node["role"],
                "kind": node["kind"],
                "artifacts": list(outputs) if node["kind"] == "activity" else [],
                "reject_to": str(node.get("reject_to") or "") if node["kind"] == "gate" else "",
            }
        )
    return {
        "workflow_id": workflow["workflow_id"],
        "workflow_gates": [node["id"] for node in visible if node.get("kind") == "gate"],
        "workflow_nodes": meta,
    }


def _explicit_outputs(value: object) -> list[dict[str, str]]:
    from geni_studio.config.workflow_defs import _output_items

    return _output_items(value)


def _template_problem(activity: str, item: dict[str, str]) -> list[str]:
    from geni_studio.config.registry import template_file_error

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
        from geni_studio.backends.runner import invoke_role
        from geni_studio.hitl.attachments import prompt_section

        sections = [f"活动：{node['name']}"]
        request = str(state.get("human_request") or "")
        if request and "human_request" not in inputs:
            sections.append(f"人类原始需求：\n{request}")
        attached = prompt_section(state.get("attachments"))
        if attached:
            sections.append(attached)
        for key in inputs:
            sections.append(f"{key}：\n{state.get(key) or ''}")
        for spec in node.get("output_specs") or []:
            sections.append(_template_section(spec))
        if node.get("returns_to"):
            sections.append("若这一活动未能通过，最后一行只写 STATUS: fail。通过则不要写这一行。")
        tools = _tool_section(_chosen_tools(state, str(node["id"])))
        if tools:
            sections.append(tools)
        body = invoke_role(
            role_name=str(node["role"]),
            user_prompt="\n\n".join(sections),
            stub_note=str(node["name"]),
        )
        parallel = bool(node.get("parallel_id"))
        if parallel:
            bucket = {
                f"{node['parallel_id']}:{node['branch_id']}:{key}": body
                for key in outputs
            }
            update = {"branch_artifacts": bucket}
        else:
            update = {key: body for key in outputs}
        counts = dict(state.get("return_counts") or {})
        target = ""
        origin = ""
        if node.get("returns_to") and _STATUS_FAIL.search(body):
            counts[node["id"]] = int(counts.get(node["id"]) or 0) + 1
            limit = node.get("max_loops")
            if not isinstance(limit, int) or limit < 1:
                limit = max_dev_retries_for_state(state)
            if counts[node["id"]] >= limit:
                target = "__escalate__"
                origin = node["id"]
            else:
                target = str(node.get("graph_return") or node["returns_to"])
        if parallel:
            update["return_counts"] = {node["id"]: counts[node["id"]]} if target else {}
            if target:
                update["return_decisions"] = {node["id"]: target}
            if origin:
                update["escalated_from"] = origin
        else:
            update["return_counts"] = counts
            update["return_target"] = target
            update["escalated_from"] = origin
        return update

    fn.__name__ = f"activity_{node['id']}"
    return fn


def _chosen_tools(state: FactoryState, node_id: str) -> dict[str, Any]:
    raw = state.get("node_tools") or {}
    if not isinstance(raw, dict):
        return {}
    item = raw.get(node_id)
    return item if isinstance(item, dict) else {}


def _tool_section(chosen: dict[str, Any]) -> str:
    skills = [str(item) for item in chosen.get("skills") or [] if str(item).strip()]
    mcp = [str(item) for item in chosen.get("mcp") or [] if str(item).strip()]
    if not skills and not mcp:
        return ""
    lines = ["这一步只使用下面列出的 Skill 和 MCP。"]
    if skills:
        lines.append("Skill：" + "、".join(_display_tool(item) for item in skills))
    if mcp:
        lines.append("MCP：" + "、".join(_display_tool(item) for item in mcp))
    return "\n".join(lines)


def _display_tool(token: str) -> str:
    scope, sep, name = token.partition(":")
    if sep and scope in {"project", "user"} and name:
        where = "项目" if scope == "project" else "用户"
        return f"{name}（{where}）"
    return token


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
        from geni_studio.hitl.gate import apply_gate_node

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


def _gate_route(nxt: str, reject: str = ""):
    key = _edge_key(nxt)
    reject_key = reject or "__end__"

    def route(state: FactoryState) -> str:
        if state.get("last_gate_decision") == "rejected":
            return reject_key
        return key

    return route


def _return_route(nxt: str, node_id: str = "", *, parallel: bool = False):
    key = _edge_key(nxt)

    def route(state: FactoryState) -> str:
        if parallel:
            target = str((state.get("return_decisions") or {}).get(node_id) or "")
        else:
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
        return _entry(executable[0])
    if matched and matched["kind"] == "end":
        return END
    return returns_to


def _prepare_flat(workflow: dict[str, Any], root: Any) -> dict[str, Any]:
    id_map: dict[str, str] = {}
    nodes: list[dict[str, Any]] = []
    for node in workflow.get("nodes") or []:
        nodes.extend(_flatten_node(node, "", root, set(), id_map, None))
    for node in _walk_steps(nodes):
        prefix = str(node.pop("_edge_prefix", "") or "")
        for key in ("returns_to", "reject_to"):
            target = str(node.get(key) or "")
            if not target or target in {"start", "end"}:
                continue
            mapped = id_map.get(f"{prefix}{target}") or id_map.get(target)
            if mapped:
                node[key] = mapped
    _bind_contracts(nodes, root)
    flat = dict(workflow)
    flat["nodes"] = nodes
    return flat


def _flatten_node(
    node: dict[str, Any],
    prefix: str,
    root: Any,
    stack: set[str],
    id_map: dict[str, str],
    branch: dict[str, str] | None,
) -> list[dict[str, Any]]:
    kind = str(node.get("kind") or "")
    if kind in {"start", "end"}:
        if prefix:
            return []
        copied = dict(node)
        id_map[str(copied["id"])] = str(copied["id"])
        return [copied]
    if kind == "subgraph":
        subgraph_id = str(node.get("subgraph_id") or "")
        if subgraph_id in stack:
            raise ConfigError("子图不能套住自己。")
        from geni_studio.config.workflow_defs import uses_default_engine

        if uses_default_engine(subgraph_id, root):
            raise ConfigError("通用软件开发不能当作子图插入。")
        loaded = get_workflow(subgraph_id, root=root)
        inner_prefix = f"{prefix}{node['id']}__"
        inner: list[dict[str, Any]] = []
        for child in loaded["workflow"]["nodes"]:
            inner.extend(
                _flatten_node(child, inner_prefix, root, stack | {subgraph_id}, id_map, branch)
            )
        real = [item for item in inner if item.get("kind") not in {"start", "end"}]
        if not real:
            raise ConfigError(f"子图「{node.get('name') or subgraph_id}」里没有可执行的步骤。")
        id_map[f"{prefix}{node['id']}"] = _entry(real[0])
        return real
    if kind == "parallel":
        parallel_id = f"{prefix}{node['id']}" if prefix else str(node["id"])
        branches: list[dict[str, Any]] = []
        for raw in node.get("branches") or []:
            info = {
                "parallel_id": parallel_id,
                "branch_id": str(raw["id"]),
                "name": str(raw["name"]),
            }
            steps: list[dict[str, Any]] = []
            branch_prefix = f"{parallel_id}__{raw['id']}__"
            for child in raw.get("nodes") or []:
                steps.extend(_flatten_node(child, branch_prefix, root, stack, id_map, info))
            steps = [step for step in steps if step.get("kind") not in {"start", "end"}]
            if not steps:
                raise ConfigError(f"「{raw['name']}」还没有活动。")
            branches.append({"id": raw["id"], "name": raw["name"], "steps": steps})
        folded = {
            "id": parallel_id,
            "kind": "parallel",
            "name": node.get("name") or parallel_id,
            "role": "",
            "returns_to": "",
            "label": node.get("name") or parallel_id,
            "fork_id": parallel_id + "__fork",
            "join_id": parallel_id + "__join",
            "branches": branches,
        }
        id_map[parallel_id] = str(folded["fork_id"])
        return [folded]
    copied = dict(node)
    copied["id"] = f"{prefix}{node['id']}" if prefix else str(node["id"])
    copied["_edge_prefix"] = prefix
    if branch:
        copied["parallel_id"] = branch["parallel_id"]
        copied["branch_id"] = branch["branch_id"]
        copied["branch_name"] = branch["name"]
        copied["label"] = f"{branch['name']} · {copied.get('name') or copied['id']}"
    else:
        copied["label"] = copied.get("label") or copied.get("name") or copied["id"]
    id_map[str(copied["id"])] = str(copied["id"])
    return [copied]


def _bind_contracts(nodes: list[dict[str, Any]], root: Any) -> None:
    allowed = set(FactoryState.__annotations__)
    errors: list[str] = []
    for node in _iter_steps(nodes):
        if node.get("kind") != "activity":
            continue
        outputs_now = node.get("outputs")
        if node.get("output_specs") or (
            isinstance(outputs_now, list) and all(isinstance(item, str) for item in outputs_now)
        ):
            continue
        inputs, outputs, problems = _activity_contract(node, root)
        errors.extend(problems)
        unknown = [item for item in [*inputs, *outputs] if item not in allowed]
        name = str(node.get("name") or node.get("id") or "")
        if unknown:
            errors.append(f"活动「{name}」使用了图状态里没有的产物：{'、'.join(unknown)}。")
        if not outputs and "outputs" not in node:
            errors.append(f"活动「{name}」缺少产出产物。")
        node["inputs"] = inputs
        node["outputs"] = outputs
    if errors:
        raise ConfigError("\n".join(errors))


def _walk_steps(nodes: list[dict[str, Any]]):
    for node in nodes:
        if node.get("kind") == "parallel":
            for branch in node.get("branches") or []:
                yield from _walk_steps(branch.get("steps") or [])
            continue
        if node.get("kind") in {"start", "end"}:
            continue
        yield node


def _iter_steps(nodes: list[dict[str, Any]]):
    yield from _walk_steps(nodes)


def _entry(node: dict[str, Any]) -> str:
    if node.get("kind") == "parallel":
        return str(node["fork_id"])
    return str(node["id"])


def _link_steps(builder, steps, tail, nodes, by_id, executable) -> None:
    for index, step in enumerate(steps):
        nxt = steps[index + 1]["id"] if index + 1 < len(steps) else tail
        if step.get("kind") == "parallel":
            for branch in step["branches"]:
                builder.add_edge(step["fork_id"], branch["steps"][0]["id"])
                _link_steps(builder, branch["steps"], step["join_id"], nodes, by_id, executable)
            builder.add_edge(step["join_id"], nxt)
        else:
            _link_one(builder, step, nxt, nodes, by_id, executable)


def _link_one(builder, node, nxt, nodes, by_id, executable) -> None:
    returns = str(node.get("returns_to") or "")
    if returns:
        node["graph_return"] = _graph_target(returns, nodes, executable)
    if node["kind"] == "gate":
        reject = str(node.get("reject_to") or "")
        reject_dest = _graph_target(reject, nodes, executable) if reject else ""
        reject_key = "__end__" if reject_dest is END or not reject_dest else str(reject_dest)
        paths = {_edge_key(nxt): nxt, "__end__": END}
        if reject_key != "__end__":
            paths[reject_key] = _node_or_end(reject_key, by_id, executable)
        builder.add_conditional_edges(node["id"], _gate_route(nxt, reject_key), paths)
        return
    if returns:
        target = _graph_target(returns, nodes, executable)
        paths = {
            _edge_key(nxt): nxt,
            target: _node_or_end(target, by_id, executable),
            _ESCALATE: _ESCALATE,
        }
        builder.add_conditional_edges(
            node["id"],
            _return_route(nxt, str(node["id"]), parallel=bool(node.get("parallel_id"))),
            paths,
        )
        return
    if nxt is END:
        builder.add_edge(node["id"], END)
    else:
        builder.add_edge(node["id"], nxt)


def _noop(state: FactoryState) -> dict[str, Any]:
    return {}


def _join(node: dict[str, Any]):
    order = [str(branch["id"]) for branch in node["branches"]]
    names = {str(branch["id"]): str(branch["name"]) for branch in node["branches"]}

    def fn(state: FactoryState) -> dict[str, Any]:
        found = state.get("branch_artifacts") or {}
        grouped: dict[str, list[tuple[str, str]]] = {}
        for branch_id in order:
            branch_prefix = f"{node['id']}:{branch_id}:"
            for key, text in found.items():
                if not str(key).startswith(branch_prefix):
                    continue
                artifact = str(key)[len(branch_prefix) :]
                grouped.setdefault(artifact, []).append((names[branch_id], str(text)))
        update: dict[str, Any] = {}
        for artifact, pairs in grouped.items():
            if len(pairs) == 1:
                update[artifact] = pairs[0][1]
            else:
                update[artifact] = "\n\n".join(f"## {title}\n{text}" for title, text in pairs)
        return update

    fn.__name__ = f"join_{node['id']}"
    return fn
