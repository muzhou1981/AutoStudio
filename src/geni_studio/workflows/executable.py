"""把项目选定的流程编译成当轮 LangGraph。"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from geni_studio.config.context import ConfigError
from geni_studio.config.workflow_defs import get_workflow
from geni_studio.roles.loader import role_contract
from geni_studio.workflows import artifacts
from geni_studio.workflows.default import (
    FactoryState,
    _with_stop_guard,
    max_dev_retries_for_state,
)

_OPTIONAL_OUTPUTS = frozenset({"change_request"})
DECISIONS = {"approve": "批准或驳回"}
_ESCALATE = "workflow_escalate"


def resolve_executable(workflow: dict[str, Any], *, root: Any = None) -> dict[str, Any]:
    """补上活动的产物契约，并拒绝缺少决定类型的决策点。"""
    errors: list[str] = []
    nodes: list[dict[str, Any]] = []
    on_branch = str(workflow.get("workspace") or "") == "current_branch"
    for raw in workflow.get("nodes") or []:
        node = dict(raw)
        kind = node.get("kind")
        name = str(node.get("name") or node.get("id") or "")
        if kind == "activity":
            inputs, outputs, problems = _activity_contract(node, root)
            errors.extend(problems)
            errors.extend(_name_problems(name, [*inputs, *outputs]))
            if not outputs and "outputs" not in node:
                errors.append(f"活动「{name}」缺少产出产物。")
            node["inputs"] = inputs
            node["outputs"] = outputs
            if on_branch:
                node["on_current_branch"] = True
        elif kind == "gate":
            decision = str(node.get("decision") or "").strip()
            if decision not in DECISIONS:
                errors.append(f"决策点「{name}」缺少决定类型。")
            node["decision"] = decision
        if node.get("id") == _ESCALATE:
            errors.append("节点标识 workflow_escalate 已留给回退升级。")
        nodes.append(node)
    runnable = [
        node for node in nodes if node.get("kind") in {"activity", "gate", "parallel", "subgraph", "system"}
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
    from geni_studio.runtime.snapshots import put

    return compiled, {**run_state(flat), "workflow_definition_ref": put(flat)}


def compile_workflow(workflow: dict[str, Any], *, checkpointer: BaseCheckpointSaver) -> Any:
    nodes = deepcopy(workflow["nodes"])
    executable = [node for node in nodes if node["kind"] not in {"start", "end"}]
    _validate_parallel(executable)
    by_id = {node["id"]: node for node in nodes}
    builder = StateGraph(FactoryState)
    for step in _iter_steps(executable):
        if step["kind"] == "activity":
            fn = _activity(step)
        elif step["kind"] == "system":
            fn = _system(step)
        else:
            fn = _gate(step)
        builder.add_node(step["id"], _with_stop_guard(_recorded(str(step["id"]), _when(step, fn))))
    for node in executable:
        if node["kind"] != "parallel":
            continue
        builder.add_node(node["fork_id"], _with_stop_guard(_fork(node)))
        builder.add_node(node["join_id"], _with_stop_guard(_recorded(str(node["join_id"]), _join(node))))
    builder.add_node(_ESCALATE, _with_stop_guard(_escalate))
    builder.add_edge(START, _entry(executable[0]))
    for index, node in enumerate(executable):
        nxt = _entry(executable[index + 1]) if index + 1 < len(executable) else END
        if node["kind"] == "parallel":
            done = []
            for branch in node["branches"]:
                marker = f"{node['id']}__{branch['id']}__done"
                done.append(marker)
                builder.add_node(marker, _with_stop_guard(_noop))
                builder.add_edge(node["fork_id"], branch["steps"][0]["id"])
                _link_steps(builder, branch["steps"], marker, nodes, by_id, executable)
            builder.add_edge(done, node["join_id"])
            builder.add_conditional_edges(
                node["join_id"], _join_route(nxt), {_edge_key(nxt): nxt, "__end__": END}
            )
        else:
            _link_one(builder, node, nxt, nodes, by_id, executable)
    builder.add_edge(_ESCALATE, END)
    gates = [step["id"] for step in _iter_steps(executable) if step["kind"] == "gate"]
    return builder.compile(checkpointer=checkpointer, interrupt_before=gates)


def _validate_parallel(nodes):
    for node in nodes:
        if node.get("kind") != "parallel":
            continue
        for branch in node["branches"]:
            for step in branch["steps"]:
                if step["kind"] != "activity" or step.get("returns_to"):
                    raise ConfigError("并行支路暂不支持人工关卡、回退或嵌套并行，请拆为顺序流程")


def _fork(node):
    def fn(state):
        prefix = f"{node['id']}:"
        update: dict[str, Any] = {"branch_artifacts": {
            key: "" for key in (state.get("branch_artifacts") or {}) if key.startswith(prefix)
        }}
        workspace = str(state.get("workspace_path") or "")
        if not workspace:
            return update
        from geni_studio.backends.runner import required_capabilities
        from geni_studio.roles.capabilities import WORKSPACE_MUTATING

        writers = [
            branch
            for branch in node["branches"]
            if any(required_capabilities(step["role"]) & WORKSPACE_MUTATING for step in _iter_steps(branch["steps"]))
        ]
        if not writers:
            return update
        from pathlib import Path

        from geni_studio.workspace.branches import add_branch_worktree, snapshot
        from geni_studio.workspace.layout import workspace_lock_root

        repo = workspace_lock_root(workspace)
        if repo is None:
            raise ConfigError("并行支路要写入或执行命令，但本轮工作区不是工厂管理的 git 工作区。")
        base = snapshot(Path(workspace))
        owner = _thread_id() or Path(workspace).name
        spaces = {f"{node['id']}:__base__": base}
        for branch in writers:
            path = add_branch_worktree(repo, owner, f"{node['id']}__{branch['id']}", base)
            spaces[f"{node['id']}:{branch['id']}"] = str(path)
        update["branch_workspaces"] = spaces
        return update
    return fn


def _system(node: dict[str, Any]):
    from geni_studio.workflows.system_nodes import handler

    name = str(node["handler"])

    def fn(state: FactoryState) -> dict[str, Any]:
        return handler(name)(state)

    fn.__name__ = name
    return fn


def _when(node: dict[str, Any], fn):
    cond = node.get("when")
    if not cond:
        return fn
    from geni_studio.workflows.system_nodes import evaluate

    def guarded(state: FactoryState) -> dict[str, Any]:
        if not evaluate(cond, dict(state)):
            return {}
        return fn(state)

    guarded.__name__ = getattr(fn, "__name__", "node")
    return guarded


def _recorded(node_id: str, fn):
    def wrapped(state: FactoryState) -> dict[str, Any]:
        update = fn(state)
        if not update:
            return update
        meta = artifacts.record(state, update, node_id, _thread_id())
        return {**update, **meta} if meta else update

    wrapped.__name__ = getattr(fn, "__name__", "node")
    return wrapped


def _thread_id() -> str:
    try:
        from langgraph.config import get_config

        return str(get_config()["configurable"].get("thread_id") or "")
    except (RuntimeError, KeyError):
        return ""


def _routed(node: dict[str, Any], default: Any) -> tuple[Any, dict[str, Any]]:
    from geni_studio.workflows.system_nodes import evaluate

    routes = [(route["when"], str(route["to"])) for route in node.get("routes") or []]
    default_key = _edge_key(default)

    def route(state: FactoryState) -> str:
        for cond, target in routes:
            if evaluate(cond, dict(state)):
                return target
        return default_key

    paths: dict[str, Any] = {default_key: default}
    for _, target in routes:
        paths[target] = target
    return route, paths


def run_state(workflow: dict[str, Any]) -> dict[str, Any]:
    if str(workflow.get("rail") or "") == "builtin":
        return {"workflow_id": workflow["workflow_id"]}
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
    if node.get("commits_on_branch"):
        if role != "developer":
            return [], [], [f"活动「{name}」只有程序员可以提交入库。"]
        return ["code_change", "delivery_report"], ["land_record"], []
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
    primary = str(node.get("primary_output") or "").strip()
    if primary:
        if primary in seen_inputs:
            problems.append(f"活动「{name}」的产物名「{primary}」重复。")
        return inputs, [primary], problems
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
    run = _activity_run(node)

    def fn(state: FactoryState) -> dict[str, Any]:
        space = ""
        if node.get("parallel_id"):
            key = f"{node['parallel_id']}:{node['branch_id']}"
            space = str((state.get("branch_workspaces") or {}).get(key) or "")
        if not space:
            return run(state)
        from geni_studio.workspace.context import use_worktree

        with use_worktree(space):
            return run({**state, "workspace_path": space})

    fn.__name__ = f"activity_{node['id']}"
    return fn


def _activity_run(node: dict[str, Any]):
    inputs = list(node.get("inputs") or [])
    outputs = list(node.get("outputs") or [])

    def fn(state: FactoryState) -> dict[str, Any]:
        from geni_studio.backends.runner import invoke_role
        from geni_studio.hitl.attachments import prompt_section

        if node.get("commits_on_branch"):
            from geni_studio.workspace.layout import commit_current_branch

            summary = str(
                state.get("delivery_report")
                or state.get("code_change")
                or state.get("human_request")
                or ""
            )
            body = commit_current_branch(
                str(state.get("workspace_path") or ""),
                str(state.get("base_branch") or ""),
                summary,
            )
            return _activity_update(node, state, outputs, body)

        sections = [f"活动：{node['name']}"]
        if node.get("on_current_branch"):
            sections.append(
                "这一步直接修改目标仓库当前检出的分支，不另建工作树。"
                "不要执行 git commit 或 git push。提交留到人类确认入库之后，由程序员完成。"
            )
        request = str(state.get("human_request") or "")
        if request and "human_request" not in inputs:
            sections.append(f"人类原始需求：\n{request}")
        attached = prompt_section(state.get("attachments"))
        if attached:
            sections.append(attached)
        feedback = str(state.get("return_feedback") or "")
        if feedback:
            sections.append(f"## 需要修复的问题\n上一轮未通过，原因如下，请逐条修复：\n{feedback}")
        for key in inputs:
            value = artifacts.read(state, key) or ""
            if node.get("parallel_id"):
                local = f"{node['parallel_id']}:{node['branch_id']}:{key}"
                value = (state.get("branch_artifacts") or {}).get(local, value)
            sections.append(artifacts.reference(state, key, key, role=str(node["role"]), value=value) or f"{key}：\n")
        for spec in node.get("output_specs") or []:
            sections.append(_template_section(spec))
        if node.get("returns_to"):
            from geni_studio.verification.verdict import VERDICT_INSTRUCTION

            sections.append(VERDICT_INSTRUCTION)
        if "change_request" in outputs:
            from geni_studio.verification.verdict import CHANGE_REQUEST_INSTRUCTION

            sections.append(CHANGE_REQUEST_INSTRUCTION)
        tools = _tool_section(_chosen_tools(state, str(node["id"])))
        if tools:
            sections.append(tools)
        body = invoke_role(
            role_name=str(node["role"]),
            user_prompt="\n\n".join(sections),
            stub_note=str(node["name"]),
        )
        verdict = None
        if node.get("returns_to") or (node["role"] == "tester" and "test_report" in outputs):
            from geni_studio.backends.runner import role_is_simulated
            from geni_studio.verification.verdict import judge

            verdict = judge(body, simulated=role_is_simulated(str(node["role"])))
        if node["role"] == "tester" and "test_report" in outputs:
            from geni_studio.verification.command import verified_report
            from geni_studio.verification.verdict import Verdict

            assert verdict is not None
            body, status = verified_report(
                state, body, verdict.status, claim_binding=verdict.source in {"block", "legacy", "invalid"}
            )
            error = (verdict.error or "验证命令未通过或缺少机器验证证据。") if status == "fail" else ""
            verdict = Verdict(status, ac=verdict.ac, summary=verdict.summary, source=verdict.source, error=error)  # type: ignore[arg-type]
            if status != "pass" and not node.get("returns_to"):
                raise RuntimeError("测试未通过且活动未配置回退去向")
        if verdict is not None:
            from geni_studio.verification.verdict import with_verdict

            body = with_verdict(body, verdict)
        return _activity_update(node, state, outputs, body, failed=verdict is not None and not verdict.passed)

    return fn


def _activity_update(
    node: dict[str, Any],
    state: FactoryState,
    outputs: list[str],
    body: str,
    *,
    failed: bool = False,
) -> dict[str, Any]:
    from geni_studio.verification.verdict import split_outputs

    parallel = bool(node.get("parallel_id"))
    values = split_outputs(body, outputs, optional=_OPTIONAL_OUTPUTS)
    if parallel:
        bucket = {
            f"{node['parallel_id']}:{node['branch_id']}:{key}": value
            for key, value in values.items()
        }
        update: dict[str, Any] = {"branch_artifacts": bucket}
    else:
        update = {}
        for key, value in values.items():
            artifacts.put(update, key, value)
        if state.get("return_feedback") and not failed:
            update["return_feedback"] = ""
    counts = dict(state.get("return_counts") or {})
    target = ""
    origin = ""
    if node.get("returns_to") and failed:
        counts[node["id"]] = int(counts.get(node["id"]) or 0) + 1
        limit = node.get("max_loops")
        if not isinstance(limit, int) or limit < 1:
            limit = max_dev_retries_for_state(state)
        if counts[node["id"]] >= limit:
            target = "__escalate__"
            origin = node["id"]
        else:
            target = str(node.get("graph_return") or node["returns_to"])
            if not parallel:
                update["return_feedback"] = f"「{node.get('label') or node['name']}」未通过：\n{body}"
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
    if "content" in spec:
        return f"输出「{name}」请按下面的模板写：\n{spec['content']}"
    from pathlib import Path

    try:
        text = Path(template).read_text(encoding="utf-8")
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
    _check_artifact_flow(nodes)
    from pathlib import Path

    for node in _iter_steps(nodes):
        for spec in node.get("output_specs") or []:
            if spec.get("source") != "link":
                spec["content"] = Path(spec["template"]).read_text(encoding="utf-8")
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
        from geni_studio.config.workflow_defs import has_system_nodes

        if has_system_nodes(subgraph_id, root):
            raise ConfigError("含系统节点的流程（例如通用软件开发）不能当作子图插入。")
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


def _name_problems(activity: str, names: list[str]) -> list[str]:
    bad = [item for item in names if artifacts.is_custom(item) and not artifacts.valid_name(item)]
    if not bad:
        return []
    return [f"活动「{activity}」的产物名不合法：{'、'.join(bad)}。自定义产物名只能用小写字母、数字和下划线，并以字母开头。"]


def _check_artifact_flow(nodes: list[dict[str, Any]]) -> None:
    """自定义产物须由流程中的某个活动产出，才能被其他活动读取。"""
    produced: set[str] = set()
    for node in _iter_steps(nodes):
        if node.get("kind") == "activity":
            produced.update(str(item) for item in node.get("outputs") or [])
    errors: list[str] = []
    for node in _iter_steps(nodes):
        if node.get("kind") != "activity":
            continue
        missing = artifacts.unknown_names([str(item) for item in node.get("inputs") or []], produced)
        if missing:
            name = str(node.get("name") or node.get("id") or "")
            errors.append(f"活动「{name}」读取的产物没有活动产出：{'、'.join(missing)}。")
    if errors:
        raise ConfigError("\n".join(errors))


def _bind_contracts(nodes: list[dict[str, Any]], root: Any) -> None:
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
        name = str(node.get("name") or node.get("id") or "")
        errors.extend(_name_problems(name, [*inputs, *outputs]))
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
    if node["kind"] == "system":
        explicit = str(node.get("next") or "")
        if explicit:
            nxt = _node_or_end(explicit, by_id, executable)
        if node.get("routes"):
            route, paths = _routed(node, nxt)
            builder.add_conditional_edges(node["id"], route, paths)
        else:
            builder.add_edge(node["id"], nxt)
        return
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


def _join_route(nxt: Any):
    key = _edge_key(nxt)

    def route(state: FactoryState) -> str:
        if state.get("hitl_pending_kind") == "escalation":
            return "__end__"
        return key

    return route


def _merge_branches(node: dict[str, Any], state: FactoryState, order: list[str], names: dict[str, str]) -> dict[str, Any]:
    """把各支路快照工作树的改动依次三方合并回本轮工作区；冲突时升级给人。"""
    spaces = state.get("branch_workspaces") or {}
    base = str(spaces.get(f"{node['id']}:__base__") or "")
    if not base:
        return {}
    from datetime import UTC, datetime
    from pathlib import Path

    from geni_studio.workspace.branches import merge_back, remove_branch_worktree
    from geni_studio.workspace.layout import workspace_lock_root

    workspace = Path(str(state.get("workspace_path") or ""))
    repo = workspace_lock_root(str(workspace))
    conflicts: list[str] = []
    for branch_id in order:
        path = str(spaces.get(f"{node['id']}:{branch_id}") or "")
        if not path:
            continue
        found = merge_back(workspace, Path(path), base)
        if found:
            conflicts.append(f"「{names[branch_id]}」：{'、'.join(found)}")
        if repo is not None:
            remove_branch_worktree(repo, Path(path))
    update: dict[str, Any] = {
        "branch_workspaces": {key: "" for key in spaces if key.startswith(f"{node['id']}:")}
    }
    if conflicts:
        summary = (
            f"并行「{node['name']}」汇合时有改动冲突，已在本轮工作区写入冲突标记："
            + "；".join(conflicts)
            + "。请处理冲突后选择继续，或暂停、终止。"
        )
        update.update(
            {
                "hitl_pending_kind": "escalation",
                "hitl_summary": summary,
                "hitl_questions": [],
                "hitl_pending_since": datetime.now(UTC).isoformat(),
                "escalated_from": str(node["join_id"]),
                "return_feedback": summary,
            }
        )
    return update


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
                artifacts.put(update, artifact, pairs[0][1])
            else:
                artifacts.put(update, artifact, "\n\n".join(f"## {title}\n{text}" for title, text in pairs))
        update.update(_merge_branches(node, state, order, names))
        return update

    fn.__name__ = f"join_{node['id']}"
    return fn
