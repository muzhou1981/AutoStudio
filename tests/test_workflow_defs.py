"""流程定义的保存与校验。"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from geni_studio.config.context import ConfigError
from geni_studio.config.workflow_defs import (
    create_workflow,
    delete_workflow,
    get_workflow,
    get_workflow_version,
    list_workflow_versions,
    list_workflows,
    save_workflow,
    workflow_usage,
)
from geni_studio.web.app import app


def _root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "roles" / "developer").mkdir(parents=True)
    (tmp_path / "roles" / "developer" / "role.md").write_text(
        "---\nname: developer\ntitle: 程序员\n---\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("geni_studio.config.workflow_defs.factory_root", lambda: tmp_path)


def test_create_lists_and_rejects_bad_graph(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _root(tmp_path, monkeypatch)
    created = create_workflow("demo", "演示", root=tmp_path)
    assert [node["name"] for node in created["workflow"]["nodes"]] == ["启动", "结束"]
    assert list_workflows(tmp_path) == [
        {"workflow_id": "demo", "title": "演示", "builtin": False, "subgraph": False, "hidden": False, "workspace": ""},
    ]
    with pytest.raises(ConfigError, match="已有同名流程"):
        create_workflow("demo", root=tmp_path)
    nodes = [
        {"id": "start", "kind": "start", "name": "启动", "role": "human", "returns_to": ""},
        {"id": "n1", "kind": "activity", "name": "开发", "role": "developer", "returns_to": ""},
        {"id": "end", "kind": "end", "name": "结束", "role": "human", "returns_to": ""},
    ]
    saved = save_workflow(
        "demo",
        {"title": "演示", "description": "一条", "nodes": nodes},
        root=tmp_path,
    )
    assert saved["workflow"]["nodes"][1]["role"] == "developer"
    hitl = [
        nodes[0],
        {"id": "n2", "kind": "activity", "name": "确认预算", "role": "human", "returns_to": ""},
        nodes[2],
    ]
    as_gate = save_workflow("demo", {"title": "演示", "nodes": hitl}, root=tmp_path)
    assert as_gate["workflow"]["nodes"][1]["kind"] == "gate"
    nodes[1]["returns_to"] = "end"
    with pytest.raises(ConfigError, match="更早的节点"):
        save_workflow("demo", {"title": "演示", "nodes": nodes}, root=tmp_path)
    nodes[1]["returns_to"] = "start"
    with pytest.raises(ConfigError, match="先写最大循环次数"):
        save_workflow("demo", {"title": "演示", "nodes": nodes}, root=tmp_path)
    nodes[1]["max_loops"] = 2
    looped = save_workflow("demo", {"title": "演示", "nodes": nodes}, root=tmp_path)
    assert looped["workflow"]["nodes"][1]["max_loops"] == 2
    with pytest.raises(ConfigError, match="字母开头"):
        create_workflow("1bad", root=tmp_path)


def test_workflow_api_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _root(tmp_path, monkeypatch)
    client = TestClient(app)
    created = client.post("/api/workflows", json={"workflow_id": "demo", "title": "演示"})
    assert created.status_code == 200
    listed = client.get("/api/workflows")
    assert listed.status_code == 200
    assert listed.json()["workflows"][0]["workflow_id"] == "demo"
    loaded = get_workflow("demo", root=tmp_path)
    assert loaded["workflow"]["title"] == "演示"
    roles = client.get("/api/workflows/roles")
    assert roles.status_code == 200
    assert roles.json()["roles"][0] == {"id": "human", "label": "人类"}
    developer = next(item for item in roles.json()["roles"] if item["id"] == "developer")
    assert developer["label"] == "程序员"
    assert developer["inputs"] == []
    assert developer["outputs"] == []



def test_copy_derives_id_from_source_without_model(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """复制流程时标识由原标识派生，不调用模型翻译标题。"""
    _root(tmp_path, monkeypatch)

    def fail():
        raise AssertionError("复制流程不应调用模型")

    monkeypatch.setattr("geni_studio.backends.base.get_default_backend", fail)
    client = TestClient(app)
    assert client.post("/api/workflows", json={"workflow_id": "demo", "title": "演示"}).status_code == 200
    first = client.post("/api/workflows/demo/copy", json={"title": "副本 · 演示"})
    assert first.status_code == 200
    assert first.json()["workflow"]["workflow_id"] == "demo-copy"
    second = client.post("/api/workflows/demo-copy/copy", json={"title": "副本 · 副本 · 演示"})
    assert second.json()["workflow"]["workflow_id"] == "demo-copy-2"

def test_editor_save_keeps_fields_without_controls(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """编辑器保存时原样带回它没有控件的字段；原文覆盖入口已经去掉。"""
    _root(tmp_path, monkeypatch)
    client = TestClient(app)
    assert client.post("/api/workflows", json={"workflow_id": "demo", "title": "演示"}).status_code == 200
    body = {
        "title": "演示",
        "workspace": "current_branch",
        "profile": {"features": {"design_track": True}, "limits": {"dev_retries": 2}},
        "nodes": [
            {"id": "start", "kind": "start", "name": "启动", "role": "human", "returns_to": ""},
            {
                "id": "n1", "kind": "activity", "name": "开发", "role": "developer", "returns_to": "",
                "instruction": "写清变更说明。", "primary_output": "code_change",
                "outputs": [{"name": "code_change", "source": "link", "template": "https://example.com/t.md"}],
            },
            {"id": "end", "kind": "end", "name": "结束", "role": "human", "returns_to": ""},
        ],
    }
    saved = client.put("/api/workflows/demo", json=body)
    assert saved.status_code == 200, saved.text
    workflow = get_workflow("demo", root=tmp_path)["workflow"]
    assert workflow["workspace"] == "current_branch"
    assert workflow["profile"] == {"features": {"design_track": True}, "limits": {"dev_retries": 2}}
    assert workflow["nodes"][1]["instruction"] == "写清变更说明。"
    assert workflow["nodes"][1]["primary_output"] == "code_change"
    assert client.put("/api/workflows/demo/raw", json={"yaml": "title: x\n"}).status_code in (404, 405)


def test_delete_plain_workflow_via_api_and_refuse_when_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC：删除整份非内置流程定义；不存在返回 404。"""
    _root(tmp_path, monkeypatch)
    create_workflow("demo", "演示", root=tmp_path)
    client = TestClient(app)
    removed = client.delete("/api/workflows/demo")
    assert removed.status_code == 200
    assert removed.json() == {"workflow_id": "demo", "deleted": True}
    assert client.get("/api/workflows/demo").status_code == 404
    assert all(item["workflow_id"] != "demo" for item in list_workflows(tmp_path))
    missing = client.delete("/api/workflows/demo")
    assert missing.status_code == 404


def test_delete_refuses_while_a_project_or_parent_still_uses_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _root(tmp_path, monkeypatch)
    create_workflow("child", "子图", root=tmp_path)
    save_workflow(
        "child",
        {"title": "子图", "subgraph": True, "nodes": [
            {"id": "start", "kind": "start", "name": "启动", "role": "human", "returns_to": ""},
            {"id": "end", "kind": "end", "name": "结束", "role": "human", "returns_to": ""},
        ]},
        root=tmp_path,
    )
    create_workflow("parent", "父流程", root=tmp_path)
    save_workflow(
        "parent",
        {"title": "父流程", "nodes": [
            {"id": "start", "kind": "start", "name": "启动", "role": "human", "returns_to": ""},
            {"id": "sub", "kind": "subgraph", "name": "引用", "role": "", "subgraph_id": "child", "returns_to": ""},
            {"id": "end", "kind": "end", "name": "结束", "role": "human", "returns_to": ""},
        ]},
        root=tmp_path,
    )
    folder = tmp_path / "workflows" / "locked"
    folder.mkdir()
    (folder / "workflow.yaml").write_text(
        "workflow_id: locked\ntitle: 内置\nbuiltin: true\nnodes:\n"
        "- {id: start, kind: start, name: 启动, role: human, returns_to: ''}\n"
        "- {id: end, kind: end, name: 结束, role: human, returns_to: ''}\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="不能删除"):
        delete_workflow("locked", root=tmp_path)
    assert (folder / "workflow.yaml").is_file()
    project = tmp_path / "projects" / "demo"
    project.mkdir(parents=True)
    (project / "project.yaml").write_text(
        "project_id: demo\ntitle: 演示项目\nworkflow:\n  profile_id: parent\n", encoding="utf-8"
    )
    assert workflow_usage("child", root=tmp_path) == {
        "projects": [],
        "workflows": [{"workflow_id": "parent", "title": "父流程"}],
    }
    with pytest.raises(ConfigError, match="流程“父流程”"):
        delete_workflow("child", root=tmp_path)
    assert (tmp_path / "workflows" / "child" / "workflow.yaml").is_file()

    client = TestClient(app)
    usage = client.get("/api/workflows/parent/usage").json()
    assert usage == {"projects": [{"project_id": "demo", "title": "演示项目"}], "workflows": []}
    refused_parent = client.delete("/api/workflows/parent")
    assert refused_parent.status_code == 400
    assert "项目“演示项目”" in refused_parent.json()["detail"]
    (project / "project.yaml").write_text("project_id: demo\ntitle: 演示项目\n", encoding="utf-8")
    removed = client.delete("/api/workflows/parent")
    assert removed.status_code == 200
    assert removed.json()["deleted"] is True
    assert client.get("/api/workflows/parent").status_code == 404
    delete_workflow("child", root=tmp_path)
    assert not (tmp_path / "workflows" / "child").exists()
    assert client.get("/api/workflows/child/usage").status_code == 404
    refused = client.delete("/api/workflows/locked")
    assert refused.status_code == 400
    assert "不能删除" in refused.json()["detail"]
    missing = client.delete("/api/workflows/missing")
    assert missing.status_code == 404


def test_check_reports_start_time_problems_without_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _root(tmp_path, monkeypatch)
    monkeypatch.setattr("geni_studio.config.context.factory_root", lambda: tmp_path)
    created = create_workflow("demo", "演示", root=tmp_path)["workflow"]
    client = TestClient(app)
    empty = client.post("/api/workflows/demo/check", json=created).json()
    assert empty == {"ok": False, "problems": ["流程里没有可执行的活动或决策点。"]}
    draft = {
        **created,
        "nodes": [
            created["nodes"][0],
            {
                "id": "n1", "kind": "activity", "name": "开发", "role": "developer", "returns_to": "",
                "inputs": [], "outputs": [{"name": "plan_doc", "source": "file", "template": ""}],
            },
            created["nodes"][1],
        ],
    }
    problems = client.post("/api/workflows/demo/check", json=draft).json()["problems"]
    assert problems == ["活动“开发”的输出“plan_doc”没有模板。"]
    assert client.post("/api/workflows/missing/check", json=draft).status_code == 404
    assert len(get_workflow("demo", root=tmp_path)["workflow"]["nodes"]) == 2


def test_saves_keep_versions_with_changes_and_skip_identical(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _root(tmp_path, monkeypatch)
    create_workflow("flow", "流程", root=tmp_path)
    assert list_workflow_versions("flow", root=tmp_path) == []
    start = {"id": "start", "kind": "start", "name": "启动", "role": "human", "returns_to": ""}
    end = {"id": "end", "kind": "end", "name": "结束", "role": "human", "returns_to": ""}
    dev = {"id": "dev", "kind": "activity", "name": "开发", "role": "developer", "returns_to": ""}
    save_workflow("flow", {"title": "流程", "nodes": [start, dev, end]}, root=tmp_path)
    save_workflow("flow", {"title": "流程", "nodes": [start, dev, end]}, root=tmp_path)
    save_workflow("flow", {"title": "改名", "nodes": [start, {**dev, "name": "实现"}, end]}, root=tmp_path)
    versions = list_workflow_versions("flow", root=tmp_path)
    assert [item["version"] for item in versions] == [3, 2, 1]
    assert versions[-1]["changes"] is None
    assert versions[1]["changes"]["added"] == ["开发"] and not versions[1]["changes"]["title"]
    assert versions[0]["title"] == "改名" and versions[0]["changes"]["title"]
    assert versions[0]["changes"]["changed"] == ["实现"] and versions[0]["changes"]["removed"] == []
    original = get_workflow_version("flow", 1, root=tmp_path)
    assert [node["id"] for node in original["workflow"]["nodes"]] == ["start", "end"]
    with pytest.raises(ConfigError, match="没有版本"):
        get_workflow_version("flow", 9, root=tmp_path)
    assert list_workflows(root=tmp_path)[0]["workflow_id"] == "flow"
    client = TestClient(app)
    assert client.get("/api/workflows/flow/versions").json()["versions"][0]["version"] == 3
    assert client.get("/api/workflows/flow/versions/2").json()["workflow"]["nodes"][1]["name"] == "开发"
    assert client.get("/api/workflows/flow/versions/9").status_code == 404
    assert client.get("/api/workflows/missing/versions").status_code == 404


def test_node_stats_merge_runs_by_top_level_node(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    from geni_studio.hitl.conversation import begin_turn, finish_turn
    from geni_studio.hitl.node_stats import top_level_node, workflow_node_stats

    monkeypatch.setattr("geni_studio.hitl.conversation.factory_root", lambda: tmp_path)
    assert top_level_node("ops__a__dev", ["ops", "op"]) == "ops"
    assert top_level_node("other", ["ops"]) == ""
    for thread_id, node in (("t1", "dev"), ("t1", "dev"), ("t2", "sub__inner"), ("t3", "dev")):
        path = begin_turn(thread_id, "developer", agent_id="a", model="m", prompt="p", node=node)
        finish_turn(path, "ok", usage={"input_tokens": 10, "output_tokens": 2})
    first = tmp_path / ".geni_studio" / "runs" / "t1" / "conversations" / "nodes" / "dev" / "001.jsonl"
    rows = [json.loads(line) for line in first.read_text(encoding="utf-8").splitlines()]
    rows[0]["at"], rows[1]["at"] = "2026-11-12T08:00:00+00:00", "2026-11-12T08:01:00+00:00"
    first.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    decisions = tmp_path / ".geni_studio" / "runs" / "t2" / "decisions.jsonl"
    decisions.write_text(
        json.dumps({"node": "gate", "kind": "gate", "decision": "rejected"}) + "\n"
        + json.dumps({"node": "sub__inner", "kind": "escalation", "decision": "continue"}) + "\n",
        encoding="utf-8",
    )
    records = [
        ("t1", {"workflow_id": "flow", "return_counts": {"dev": 2}}),
        ("t2", {"workflow_id": "flow", "return_counts": {}}),
        ("t3", {"workflow_id": "elsewhere"}),
    ]
    stats = workflow_node_stats(records, "flow", ["dev", "sub", "gate"])
    assert stats["runs"] == 2
    dev, sub, gate = (stats["nodes"][key] for key in ("dev", "sub", "gate"))
    assert dev["runs"] == 1 and dev["turns"] == 2 and dev["returns"] == 2
    assert dev["input_tokens"] == 20 and dev["output_tokens"] == 4
    assert dev["avg_seconds"] is not None and dev["avg_seconds"] >= 30
    assert sub["turns"] == 1 and sub["escalations"] == 1 and sub["runs"] == 1
    assert gate["rejections"] == 1 and gate["turns"] == 0
    assert TestClient(app).get("/api/workflows/missing/stats").status_code == 404
