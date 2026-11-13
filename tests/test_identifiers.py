"""项目与流程标识按名称生成。"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from geni_studio.config.identifiers import allocate_identifier
from geni_studio.web.app import app


@pytest.fixture
def no_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """生成标识不得调用模型后端。"""

    def fail():
        raise AssertionError("生成标识不应调用模型")

    monkeypatch.setattr("geni_studio.backends.base.get_default_backend", fail)


def test_allocate_keeps_valid_id_and_slugifies_ascii() -> None:
    assert allocate_identifier("Demo_001", prefix="project", taken=[]) == "Demo_001"
    assert allocate_identifier("Hello World", prefix="project", taken=[]) == "hello-world"
    assert allocate_identifier("Hello World", prefix="project", taken=["hello-world"]) == "hello-world-2"


def test_allocate_uses_serial_for_chinese(no_model: None) -> None:
    assert allocate_identifier("预览流程", prefix="project", taken=[]) == "project-1"
    assert allocate_identifier("预览流程", prefix="workflow", taken=["workflow-1"]) == "workflow-2"
    assert allocate_identifier("前端 Bug 修复", prefix="workflow", taken=[]) == "workflow-1"
    assert allocate_identifier("!!!", prefix="role", taken=[]) == "role-1"


def test_create_project_from_title(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_model: None) -> None:
    (tmp_path / "scenarios" / "npu_operator").mkdir(parents=True)
    (tmp_path / "scenarios" / "npu_operator" / "scenario.yaml").write_text(
        "scenario_key: npu_operator\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("geni_studio.config.registry.factory_root", lambda: tmp_path)
    client = TestClient(app)
    created = client.post("/api/config/projects", json={"title": "预览项目"})
    assert created.status_code == 200
    assert created.json()["project_id"] == "project-1"
    assert (tmp_path / "projects" / "project-1" / "project.yaml").is_file()
    missing = client.post("/api/config/projects", json={})
    assert missing.status_code == 400


def test_create_workflow_from_title(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, no_model: None) -> None:
    (tmp_path / "roles" / "developer").mkdir(parents=True)
    (tmp_path / "roles" / "developer" / "role.md").write_text(
        "---\nname: developer\ntitle: 程序员\n---\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("geni_studio.config.workflow_defs.factory_root", lambda: tmp_path)
    client = TestClient(app)
    created = client.post("/api/workflows", json={"title": "预览流程"})
    assert created.status_code == 200
    assert created.json()["workflow"]["workflow_id"] == "workflow-1"
    assert created.json()["workflow"]["title"] == "预览流程"
    kept = client.post("/api/workflows", json={"title": "Demo_001"})
    assert kept.status_code == 200
    assert kept.json()["workflow"]["workflow_id"] == "Demo_001"
