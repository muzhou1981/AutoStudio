"""流程定义的保存与校验。"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from geni_studio.config.context import ConfigError
from geni_studio.config.workflow_defs import (
    create_workflow,
    delete_workflow,
    get_workflow,
    list_workflows,
    save_workflow,
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
        {"workflow_id": "demo", "title": "演示", "builtin": False, "engine": "", "subgraph": False},
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


def test_delete_removes_the_workflow_and_keeps_a_referencing_parent(
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
    delete_workflow("child", root=tmp_path)
    assert not (tmp_path / "workflows" / "child").exists()
    assert [item["workflow_id"] for item in list_workflows(tmp_path)] == ["locked", "parent"]
    with pytest.raises(ConfigError, match="流程不存在"):
        get_workflow("child", root=tmp_path)
    parent_text = (tmp_path / "workflows" / "parent" / "workflow.yaml").read_text(encoding="utf-8")
    assert "subgraph_id: child" in parent_text

    client = TestClient(app)
    removed = client.delete("/api/workflows/parent")
    assert removed.status_code == 200
    assert removed.json()["deleted"] is True
    assert client.get("/api/workflows/parent").status_code == 404
    refused = client.delete("/api/workflows/locked")
    assert refused.status_code == 400
    assert "不能删除" in refused.json()["detail"]
    missing = client.delete("/api/workflows/missing")
    assert missing.status_code == 404
