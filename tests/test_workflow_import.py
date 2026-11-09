"""导入流程文件。"""

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from geni_studio.config.context import ConfigError
from geni_studio.config.workflow_defs import import_workflow
from geni_studio.web.app import app


def _root(tmp_path: Path) -> Path:
    for role_id, title in (("developer", "程序员"), ("tester", "测试")):
        role = tmp_path / "roles" / role_id
        role.mkdir(parents=True)
        (role / "role.md").write_text(f"---\ntitle: {title}\n---\n", encoding="utf-8")
    return tmp_path


def _sample() -> str:
    return """
workflow_id: recorded_flow
title: 记录下来
builtin: true
engine: default
nodes:
  - id: start
    kind: start
    name: 启动
    role: human
  - id: change
    kind: activity
    name: 改代码
    role: developer
  - id: end
    kind: end
    name: 结束
    role: human
"""


def test_import_strips_builtin_and_keeps_steps(tmp_path: Path) -> None:
    root = _root(tmp_path)
    saved = import_workflow(_sample(), root)
    data = saved["workflow"]
    assert data["workflow_id"] == "recorded_flow"
    assert data["title"] == "记录下来"
    assert "builtin" not in data
    assert "engine" not in data
    assert [node["name"] for node in data["nodes"]] == ["启动", "改代码", "结束"]
    on_disk = yaml.safe_load((root / "workflows" / "recorded_flow" / "workflow.yaml").read_text(encoding="utf-8"))
    assert "builtin" not in on_disk


def test_import_renames_when_the_id_is_taken(tmp_path: Path) -> None:
    root = _root(tmp_path)
    import_workflow(_sample(), root)
    again = import_workflow(_sample(), root)
    assert again["workflow"]["workflow_id"] != "recorded_flow"
    assert again["workflow"]["title"] == "记录下来"


def test_import_rejects_broken_yaml(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="YAML"):
        import_workflow("title: [\n", _root(tmp_path))


def test_import_route(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _root(tmp_path)
    monkeypatch.setattr("geni_studio.config.workflow_defs.factory_root", lambda: root)
    monkeypatch.setattr("geni_studio.web.workflow_routes.factory_root", lambda: root, raising=False)
    response = TestClient(app).post("/api/workflows/import", json={"yaml": _sample()})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["workflow"]["workflow_id"] == "recorded_flow"
    assert (root / "workflows" / "recorded_flow" / "workflow.yaml").is_file()
