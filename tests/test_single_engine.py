"""单一引擎：内置流程由 factory_default.yaml 编译，系统节点与条件路由（D1）。"""

from __future__ import annotations

import copy

import pytest
from langgraph.checkpoint.memory import MemorySaver

from geni_studio.config.context import ConfigError
from geni_studio.config.workflow_defs import validate_workflow
from geni_studio.workflows import default as default_module
from geni_studio.workflows.default import (
    _BUILTIN_ROOT,
    builtin_definition,
    compile_graph,
)
from geni_studio.workflows.executable import (
    _prepare_flat,
    compile_workflow,
    resolve_executable,
)
from geni_studio.workflows.system_nodes import EFFECTS, HANDLERS


def _compile(nodes):
    flow = {"workflow_id": "variant", "title": "变体", "nodes": nodes}
    clean = validate_workflow(flow, root=_BUILTIN_ROOT)
    flat = _prepare_flat(resolve_executable(clean, root=_BUILTIN_ROOT), _BUILTIN_ROOT)
    return compile_workflow(flat, checkpointer=MemorySaver())


def _builtin_nodes():
    from geni_studio.config.workflow_defs import get_workflow

    return copy.deepcopy(get_workflow("factory_default", root=_BUILTIN_ROOT)["workflow"]["nodes"])


def test_default_graph_is_compiled_from_the_yaml():
    definition = builtin_definition()
    handlers = {node["handler"] for node in definition["nodes"] if node["kind"] == "system"}
    assert handlers == HANDLERS
    effects = {node["effect"] for node in definition["nodes"] if node.get("effect")}
    assert effects == EFFECTS == set(default_module.EFFECTS)
    graph = compile_graph(MemorySaver()).get_graph()
    names = set(graph.nodes)
    assert HANDLERS <= names
    assert {"gate_requirement_confirm", "gate_architecture_review", "gate_final_delivery"} <= names


def test_default_flow_agent_steps_use_the_chosen_tools(monkeypatch):
    prompts: list[tuple[str, str]] = []

    def fake_invoke(*, role_name: str, user_prompt: str, stub_note: str, **_: object) -> str:
        prompts.append((role_name, user_prompt))
        return f"[stub:{role_name}] {stub_note}"

    monkeypatch.setattr("geni_studio.backends.runner.invoke_role", fake_invoke)
    graph = compile_graph(MemorySaver())
    config = {"configurable": {"thread_id": "tools"}}
    graph.invoke(
        {
            "human_request": "做一个工具",
            "node_tools": {
                "project_manager_draft": {"skills": ["project:brainstorming"], "mcp": ["user-geni-wiki"]},
                "tester_testability": {"skills": ["user:grill-me"], "mcp": []},
            },
        },
        config,
    )
    draft = next(prompt for role, prompt in prompts if role == "project_manager")
    assert "这一步优先使用下面的 Skill：brainstorming（项目）" in draft
    assert "user-geni-wiki" not in draft, "MCP 是全局配置，提示词不再列出"
    assert "验收标准 AC-*" in draft and "`requirement_spec`" in draft
    review = next(prompt for role, prompt in prompts if role == "tester")
    assert "grill-me（用户）" in review and "brainstorming" not in review


def test_plain_outputs_from_the_role_contract_need_no_template():
    def flow(outputs):
        return [
            {"id": "start", "kind": "start", "name": "启动", "role": "human"},
            {"id": "arch", "kind": "activity", "name": "架构", "role": "architect", "outputs": outputs},
            {"id": "end", "kind": "end", "name": "结束", "role": "human"},
        ]

    _compile(flow(["architecture_design", "task_plan"]))
    with pytest.raises(ConfigError, match="输出「ux_spec」没有模板"):
        _compile(flow(["ux_spec"]))
    with pytest.raises(ConfigError, match="输出「task_plan」没有模板"):
        _compile(flow([{"name": "task_plan", "source": "file", "template": ""}]))


def test_removing_a_node_in_the_yaml_changes_the_run():
    nodes = [node for node in _builtin_nodes() if node["id"] != "tester_testability"]
    graph = _compile(nodes)
    config = {"configurable": {"thread_id": "t1"}}
    graph.invoke({"human_request": "做一个工具"}, config)
    snap = graph.get_state(config)
    assert snap.next == ("gate_requirement_confirm",)
    assert snap.values.get("requirement_spec")
    assert not snap.values.get("testability_review")


def test_when_condition_skips_the_design_track():
    graph = compile_graph(MemorySaver())
    for enabled, expect in ((True, True), (False, False)):
        config = {"configurable": {"thread_id": f"design-{enabled}"}}
        graph.invoke({"human_request": "x", "design_track_enabled": enabled}, config)
        graph.update_state(config, {"gate_decision": "approved"})
        graph.invoke(None, config)
        snap = graph.get_state(config)
        assert snap.next == ("gate_architecture_review",)
        assert bool(snap.values.get("ux_spec")) is expect


def test_activity_when_condition_is_honoured():
    nodes = [
        {"id": "start", "kind": "start", "name": "启动", "role": "human"},
        {"id": "draft", "kind": "activity", "name": "起草", "role": "project_manager", "primary_output": "requirement_spec"},
        {
            "id": "budget",
            "kind": "activity",
            "name": "预算",
            "role": "finance",
            "when": "feature:finance",
            "primary_output": "budget_plan",
        },
        {"id": "end", "kind": "end", "name": "结束", "role": "human"},
    ]
    graph = _compile(nodes)
    for finance, expect in ((False, False), (True, True)):
        config = {"configurable": {"thread_id": f"fin-{finance}"}}
        graph.invoke({"human_request": "x", "finance_enabled": finance}, config)
        assert bool(graph.get_state(config).values.get("budget_plan")) is expect


def test_system_node_validation():
    base = _builtin_nodes()
    bad_handler = copy.deepcopy(base)
    next(node for node in bad_handler if node["id"] == "pm_clarification_check")["handler"] = "nope"
    with pytest.raises(ConfigError, match="实现「nope」不存在"):
        validate_workflow({"workflow_id": "x", "nodes": bad_handler}, root=_BUILTIN_ROOT)
    bad_effect = copy.deepcopy(base)
    next(node for node in bad_effect if node["id"] == "qa")["effect"] = "nope"
    with pytest.raises(ConfigError, match="内置后处理「nope」不存在"):
        validate_workflow({"workflow_id": "x", "nodes": bad_effect}, root=_BUILTIN_ROOT)
    both = copy.deepcopy(base)
    reviewer = next(node for node in both if node["id"] == "code_reviewer")
    reviewer["returns_to"], reviewer["max_loops"] = "developer", 2
    with pytest.raises(ConfigError, match="已写回退"):
        validate_workflow({"workflow_id": "x", "nodes": both}, root=_BUILTIN_ROOT)
    bad_route = copy.deepcopy(base)
    next(node for node in bad_route if node["id"] == "change_control")["routes"][0]["to"] = "nowhere"
    with pytest.raises(ConfigError, match="去向「nowhere」"):
        validate_workflow({"workflow_id": "x", "nodes": bad_route}, root=_BUILTIN_ROOT)
    bad_cond = copy.deepcopy(base)
    next(node for node in bad_cond if node["id"] == "ux_designer")["when"] = "feature:unknown"
    with pytest.raises(ConfigError, match="未知的开关"):
        validate_workflow({"workflow_id": "x", "nodes": bad_cond}, root=_BUILTIN_ROOT)


def test_project_choosing_factory_default_runs_through_the_compiler(tmp_path, monkeypatch):
    from geni_studio.hitl.service import GraphRunService

    (tmp_path / "projects" / "p").mkdir(parents=True)
    (tmp_path / "projects" / "p" / "project.yaml").write_text(
        "project_id: p\ntitle: p\nworkflow:\n  profile_id: factory_default\n", encoding="utf-8"
    )
    for name in ("workflows", "roles"):
        (tmp_path / name).symlink_to(_BUILTIN_ROOT / name)
    for target in (
        "geni_studio.config.context.factory_root",
        "geni_studio.config.registry.factory_root",
        "geni_studio.config.workflow_defs.factory_root",
    ):
        monkeypatch.setattr(target, lambda: tmp_path)
    monkeypatch.setattr("geni_studio.config.precheck.precheck_scenario_materials", lambda *a, **k: None)
    monkeypatch.setattr("geni_studio.hitl.service.workspace_enabled", lambda: False)
    svc = GraphRunService(compile_graph(MemorySaver()))
    st = svc.start(human_request="通用", project_id="p")
    assert st.values["workflow_id"] == "factory_default"
    assert st.values["workflow_definition_ref"]
    assert "workflow_nodes" not in st.values
    assert st.awaiting_human is not None and st.awaiting_human.gate_id == "gate_requirement_confirm"
    st = svc.submit_hitl(st.thread_id, gate_decision="approved")
    assert st.awaiting_human is not None and st.awaiting_human.gate_id == "gate_architecture_review"
    assert st.values.get("ux_spec")


def test_system_workflow_cannot_be_a_subgraph():
    nodes = [
        {"id": "start", "kind": "start", "name": "启动", "role": "human"},
        {"id": "inner", "kind": "subgraph", "name": "通用", "subgraph_id": "factory_default"},
        {"id": "end", "kind": "end", "name": "结束", "role": "human"},
    ]
    with pytest.raises(ConfigError, match="不能当作子图"):
        validate_workflow({"workflow_id": "outer", "nodes": nodes}, root=_BUILTIN_ROOT)
