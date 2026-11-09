"""流程定义的保存与校验。"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from geni_studio.config.context import ConfigError
from geni_studio.config.workflow_defs import (
    create_workflow,
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
