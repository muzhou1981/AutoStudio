"""项目与流程标识按名称生成。"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from auto_studio.config.identifiers import allocate_identifier
from auto_studio.web.app import app


def test_allocate_keeps_valid_id_and_slugifies_ascii() -> None:
    assert allocate_identifier("Demo_001", prefix="project", taken=[], translate=lambda _text: "") == "Demo_001"
    assert allocate_identifier("Hello World", prefix="project", taken=[], translate=lambda _text: "") == "hello-world"


def test_allocate_translates_chinese_and_suffixes_collisions() -> None:
    taken = ["preview-workflow", "preview-workflow-2"]
    got = allocate_identifier(
        "预览流程",
        prefix="workflow",
        taken=taken,
        translate=lambda _text: "Preview Workflow",
    )
    assert got == "preview-workflow-3"


def test_allocate_falls_back_when_translation_fails() -> None:
    assert allocate_identifier("预览流程", prefix="project", taken=[], translate=lambda _text: "") == "project-1"
    assert (
        allocate_identifier("预览流程", prefix="workflow", taken=["workflow-1"], translate=lambda _text: "!!!")
        == "workflow-2"
    )

    def boom(_text: str) -> str:
        raise RuntimeError("model down")

    assert allocate_identifier("预览项目", prefix="project", taken=["project-1"], translate=boom) == "project-2"


def test_create_project_from_title(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "scenarios" / "npu_operator").mkdir(parents=True)
    (tmp_path / "scenarios" / "npu_operator" / "scenario.yaml").write_text(
        "scenario_key: npu_operator\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("auto_studio.config.registry.factory_root", lambda: tmp_path)
    monkeypatch.setattr(
        "auto_studio.config.identifiers.backend_translate",
        lambda _text: "Preview Project",
    )
    client = TestClient(app)
    created = client.post("/api/config/projects", json={"title": "预览项目"})
    assert created.status_code == 200
    assert created.json()["project_id"] == "preview-project"
    assert (tmp_path / "projects" / "preview-project" / "project.yaml").is_file()
    missing = client.post("/api/config/projects", json={})
    assert missing.status_code == 400


def test_create_workflow_from_title(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "roles" / "developer").mkdir(parents=True)
    (tmp_path / "roles" / "developer" / "role.md").write_text(
        "---\nname: developer\ntitle: 程序员\n---\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("auto_studio.config.workflow_defs.factory_root", lambda: tmp_path)
    monkeypatch.setattr(
        "auto_studio.config.identifiers.backend_translate",
        lambda _text: "",
    )
    client = TestClient(app)
    created = client.post("/api/workflows", json={"title": "预览流程"})
    assert created.status_code == 200
    assert created.json()["workflow"]["workflow_id"] == "workflow-1"
    assert created.json()["workflow"]["title"] == "预览流程"
    kept = client.post("/api/workflows", json={"title": "Demo_001"})
    assert kept.status_code == 200
    assert kept.json()["workflow"]["workflow_id"] == "Demo_001"
