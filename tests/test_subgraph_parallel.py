"""子图、并行支路，以及驳回后前往已有节点。"""

import threading
import time
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import MemorySaver

from geni_studio.config.context import ConfigError
from geni_studio.config.workflow_defs import (
    get_workflow,
    list_workflows,
    save_as_subgraph,
    save_workflow,
)
from geni_studio.hitl.service import GraphRunService
from geni_studio.workflows.default import compile_graph
from geni_studio.workflows.executable import compile_for_project


def test_builtin_subgraphs_are_listed_and_the_fullnet_calls_npu() -> None:
    listed = {item["workflow_id"]: item for item in list_workflows()}
    assert listed["npu_operator_dev"]["builtin"] is True
    assert listed["npu_operator_dev"]["subgraph"] is True
    assert listed["npu_operator_dev"]["title"] == "NPU 算子开发"
    assert listed["npu_operator_cca"]["builtin"] is True
    assert listed["npu_operator_cca"]["subgraph"] is True
    assert listed["npu_operator_aom"]["subgraph"] is True
    parent = get_workflow("npu_operator_dev")["workflow"]
    assert [node["subgraph_id"] for node in parent["nodes"] if node["kind"] == "subgraph"] == [
        "npu_operator_cca",
        "npu_operator_aom",
    ]
    assert next(node for node in parent["nodes"] if node["id"] == "confirm_cca")["reject_to"] == "confirm_aom"
    assert next(node for node in parent["nodes"] if node["id"] == "confirm_aom")["reject_to"] == "review"
    fullnet = listed["llm_fullnet"]
    assert fullnet["builtin"] is True
    assert fullnet["subgraph"] is True
    assert fullnet["title"] == "大语言模型整网适配或推理框架适配"
    loaded = get_workflow("llm_fullnet")["workflow"]
    assert "插入 NPU 算子开发子图" in loaded["description"]
    parallel = next(node for node in loaded["nodes"] if node["kind"] == "parallel")
    assert [branch["name"] for branch in parallel["branches"]] == ["算子甲", "算子乙"]
    assert parallel["branches"][0]["nodes"][0]["subgraph_id"] == "npu_operator_dev"
    # 目录中仍可查看与编辑，但不能把含人工关卡的并行图当作可执行能力。
    with pytest.raises(ConfigError, match="并行支路暂不支持"):
        compile_for_project("llm_fullnet", checkpointer=MemorySaver())


def test_parallel_branches_run_together(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _root(tmp_path)
    _patch(monkeypatch, tmp_path)
    (tmp_path / "workflows" / "sample").mkdir(parents=True)
    (tmp_path / "workflows" / "sample" / "workflow.yaml").write_text(
        "workflow_id: sample\ntitle: 并行\nnodes:\n"
        "- {id: start, kind: start, name: 启动, role: human, returns_to: ''}\n"
        "- id: both\n  kind: parallel\n  name: 两路\n  role: ''\n  returns_to: ''\n  branches:\n"
        "  - id: b1\n    name: 实现甲\n    nodes:\n"
        "    - {id: a1, kind: activity, name: 甲, role: developer, returns_to: ''}\n"
        "  - id: b2\n    name: 实现乙\n    nodes:\n"
        "    - {id: a2, kind: activity, name: 乙, role: tester, returns_to: ''}\n"
        "- {id: gate, kind: gate, name: 确认, role: human, returns_to: '', decision: approve}\n"
        "- {id: end, kind: end, name: 结束, role: human, returns_to: ''}\n",
        encoding="utf-8",
    )
    current = {"n": 0}
    peak = {"n": 0}
    lock = threading.Lock()

    def fake_invoke(*, role_name: str, user_prompt: str, stub_note: str, model: str | None = None) -> str:
        with lock:
            current["n"] += 1
            peak["n"] = max(peak["n"], current["n"])
        time.sleep(0.05)
        with lock:
            current["n"] -= 1
        return f"[{role_name}]"

    monkeypatch.setattr("geni_studio.backends.runner.invoke_role", fake_invoke)
    svc = GraphRunService(compile_graph(MemorySaver()))
    started = svc.start(human_request="并行", scenario_key="demo", project_id="bound")
    assert started.phase == "awaiting_human"
    assert peak["n"] >= 2
    assert "[developer]" in started.values["code_change"]
    assert "[tester]" in started.values["test_report"]
    assert "实现甲" in started.values["code_change"] or started.values["code_change"].startswith("[developer]")


def test_reject_goes_to_the_chosen_node(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _root(tmp_path)
    _patch(monkeypatch, tmp_path)
    (tmp_path / "workflows" / "sample").mkdir(parents=True)
    (tmp_path / "workflows" / "sample" / "workflow.yaml").write_text(
        "workflow_id: sample\ntitle: 条件\nnodes:\n"
        "- {id: start, kind: start, name: 启动, role: human, returns_to: ''}\n"
        "- {id: n1, kind: activity, name: 起草, role: project_manager, returns_to: ''}\n"
        "- {id: gate, kind: gate, name: 确认, role: human, returns_to: '', decision: approve, reject_to: n1}\n"
        "- {id: end, kind: end, name: 结束, role: human, returns_to: ''}\n",
        encoding="utf-8",
    )
    calls = {"n": 0}

    def fake_invoke(*, role_name: str, user_prompt: str, stub_note: str, model: str | None = None) -> str:
        calls["n"] += 1
        return f"第{calls['n']}次"

    monkeypatch.setattr("geni_studio.backends.runner.invoke_role", fake_invoke)
    svc = GraphRunService(compile_graph(MemorySaver()))
    started = svc.start(human_request="驳回", scenario_key="demo", project_id="bound")
    assert started.awaiting_human is not None
    assert started.awaiting_human.gate_id == "gate"
    again = svc.submit_hitl(started.thread_id, gate_decision="rejected", human_reply="重写")
    assert again.phase == "awaiting_human"
    assert again.awaiting_human is not None
    assert again.awaiting_human.gate_id == "gate"
    assert calls["n"] == 2
    assert "第2次" in again.values["requirement_spec"]


def test_save_as_subgraph_keeps_the_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "roles" / "developer").mkdir(parents=True)
    (tmp_path / "roles" / "developer" / "role.md").write_text(
        "---\nname: developer\ntitle: 程序员\noutputs: [code_change]\n---\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("geni_studio.config.workflow_defs.factory_root", lambda: tmp_path)
    nodes = [
        {"id": "start", "kind": "start", "name": "启动", "role": "human", "returns_to": ""},
        {"id": "n1", "kind": "activity", "name": "开发", "role": "developer", "returns_to": ""},
        {"id": "end", "kind": "end", "name": "结束", "role": "human", "returns_to": ""},
    ]
    from geni_studio.config.workflow_defs import create_workflow

    create_workflow("demo", "演示", root=tmp_path)
    save_workflow("demo", {"title": "演示", "nodes": nodes}, root=tmp_path)
    saved = save_as_subgraph("算子", nodes, "可复用", workflow_id="op_dev", root=tmp_path)
    assert saved["workflow"]["subgraph"] is True
    assert saved["workflow"]["workflow_id"] == "op_dev"
    assert get_workflow("demo", root=tmp_path)["workflow"]["title"] == "演示"
    assert "subgraph" not in get_workflow("demo", root=tmp_path)["workflow"]
    with pytest.raises(ConfigError, match="并行至少要有两条支路"):
        save_workflow(
            "demo",
            {
                "title": "演示",
                "nodes": [
                    nodes[0],
                    {"id": "p", "kind": "parallel", "name": "并行", "branches": [{"id": "b1", "name": "仅此", "nodes": [nodes[1]]}]},
                    nodes[2],
                ],
            },
            root=tmp_path,
        )


def _root(tmp_path: Path) -> None:
    (tmp_path / "scenarios" / "demo").mkdir(parents=True)
    (tmp_path / "scenarios" / "demo" / "scenario.yaml").write_text("scenario_key: demo\ntitle: 演示\n", encoding="utf-8")
    (tmp_path / "projects" / "bound").mkdir(parents=True)
    (tmp_path / "projects" / "bound" / "project.yaml").write_text(
        "project_id: bound\ntitle: 绑定\nscenario_key: demo\nworkflow:\n  profile_id: sample\n",
        encoding="utf-8",
    )
    for role, outputs in (
        ("project_manager", "[requirement_spec]"),
        ("developer", "[code_change]"),
        ("tester", "[test_report]"),
    ):
        folder = tmp_path / "roles" / role
        folder.mkdir(parents=True)
        (folder / "role.md").write_text(
            f"---\nname: {role}\ntitle: {role}\noutputs: {outputs}\n---\n",
            encoding="utf-8",
        )


def _patch(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("geni_studio.config.context.factory_root", lambda: tmp_path)
    monkeypatch.setattr("geni_studio.config.registry.factory_root", lambda: tmp_path)
    monkeypatch.setattr("geni_studio.config.workflow_defs.factory_root", lambda: tmp_path)
    monkeypatch.setattr("geni_studio.config.precheck.precheck_scenario_materials", lambda *args, **kwargs: None)
    monkeypatch.setattr("geni_studio.hitl.service.workspace_enabled", lambda: False)
