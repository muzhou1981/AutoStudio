"""角色的增加、修改和删除。"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from geni_studio.config.context import ConfigError
from geni_studio.roles.admin import create_role, delete_role, get_role, save_role
from geni_studio.web.app import app


def _root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "roles").mkdir()
    (tmp_path / "workflows").mkdir()
    monkeypatch.setattr("geni_studio.roles.admin.factory_root", lambda: tmp_path)
    monkeypatch.setattr("geni_studio.config.context.factory_root", lambda: tmp_path)


def test_create_save_and_refuse_delete_while_a_workflow_uses_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _root(tmp_path, monkeypatch)
    created = create_role("helper", root=tmp_path)
    assert created["id"] == "helper"
    assert created["category"] == "execution"
    with pytest.raises(ConfigError, match="先写一条职责"):
        save_role("helper", {"title": "助手", "category": "execution", "body": "原则"}, root=tmp_path)
    saved = save_role(
        "helper",
        {
            "title": "助手",
            "category": "management",
            "responsibilities": ["看边界"],
            "inputs": [],
            "outputs": ["qa_report"],
            "capabilities": [],
            "body": "只写结论。",
        },
        root=tmp_path,
    )
    assert saved["title"] == "助手"
    assert saved["category"] == "management"
    assert get_role("helper", root=tmp_path)["outputs"] == ["qa_report"]
    (tmp_path / "workflows" / "parent").mkdir()
    (tmp_path / "workflows" / "child").mkdir()
    (tmp_path / "workflows" / "child" / "workflow.yaml").write_text(
        "workflow_id: child\ntitle: 子图\nnodes:\n"
        "- {id: n1, kind: activity, name: 把关, role: helper}\n",
        encoding="utf-8",
    )
    (tmp_path / "workflows" / "parent" / "workflow.yaml").write_text(
        "workflow_id: parent\ntitle: 父流程\nnodes:\n"
        "- id: both\n  kind: parallel\n  name: 两路\n  branches:\n"
        "  - id: b1\n    name: 甲\n    nodes:\n"
        "    - {id: sub, kind: subgraph, name: 子图, subgraph_id: child, role: ''}\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="这个角色还在流程里：子图、父流程。先从这些流程里去掉。"):
        delete_role("helper", root=tmp_path)
    (tmp_path / "workflows" / "child" / "workflow.yaml").write_text(
        "workflow_id: child\ntitle: 子图\nnodes: []\n",
        encoding="utf-8",
    )
    (tmp_path / "workflows" / "parent" / "workflow.yaml").write_text(
        "workflow_id: parent\ntitle: 父流程\nnodes: []\n",
        encoding="utf-8",
    )
    delete_role("helper", root=tmp_path)
    with pytest.raises(ConfigError, match="角色不存在"):
        get_role("helper", root=tmp_path)


def test_role_api_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _root(tmp_path, monkeypatch)
    client = TestClient(app)
    created = client.post("/api/roles", json={"title": ""})
    assert created.status_code == 400
    assert created.json()["detail"] == "先写标题。"
    made = client.post("/api/roles", json={"title": "helper"})
    assert made.status_code == 200
    role_id = made.json()["role"]["id"]
    saved = client.put(
        f"/api/roles/{role_id}",
        json={
            "title": "助手",
            "category": "execution",
            "responsibilities": ["写说明"],
            "inputs": ["requirement_spec"],
            "outputs": ["code_change"],
            "capabilities": ["read_files"],
            "body": "先读再写。",
        },
    )
    assert saved.status_code == 200
    assert saved.json()["role"]["used_by"] == []
    listed = client.get("/api/roles")
    assert any(item["id"] == role_id for item in listed.json()["roles"])
    assert any(item["id"] == "code_change" for item in listed.json()["artifacts"])
