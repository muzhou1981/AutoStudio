"""Web 配置 API 与 registry 测试。"""

from fastapi.testclient import TestClient

from auto_studio.config.registry import (
    effective_config_summary,
    list_projects,
    list_scenarios,
    save_project_yaml,
)
from auto_studio.web.app import app


def test_list_scenarios_and_projects():
    scenarios = list_scenarios()
    assert any(s.scenario_key == "npu_operator" for s in scenarios)
    projects = list_projects()
    assert any(p.project_id == "_example" for p in projects)


def test_effective_config_example_project():
    eff = effective_config_summary(project_id="_example")
    assert eff["scenario_key"] == "npu_operator"
    assert eff["max_dev_retries"] == 5


def test_config_api_lists():
    client = TestClient(app)
    r = client.get("/api/config/scenarios")
    assert r.status_code == 200
    assert "npu_operator" in {x["scenario_key"] for x in r.json()["scenarios"]}
    r2 = client.get("/api/config/projects")
    assert r2.status_code == 200
    assert "_example" in {x["project_id"] for x in r2.json()["projects"]}


def test_config_api_settings():
    client = TestClient(app)
    r = client.get("/api/config/settings")
    assert r.status_code == 200
    assert "keys" in r.json()


def test_config_page_and_static():
    client = TestClient(app)
    assert client.get("/config").status_code == 200
    assert client.get("/static/shared.css").status_code == 200


def test_save_project_tmp_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "auto_studio.config.registry.factory_root",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        "auto_studio.config.context.factory_root",
        lambda: tmp_path,
    )
    (tmp_path / "scenarios" / "npu_operator").mkdir(parents=True)
    (tmp_path / "scenarios" / "npu_operator" / "scenario.yaml").write_text(
        "scenario_key: npu_operator\nworkflow:\n  skip_nodes: []\n",
        encoding="utf-8",
    )
    yaml_text = "project_id: webtest\ntitle: t\nscenario_key: npu_operator\n"
    save_project_yaml("webtest", yaml_text, root=tmp_path, create=True)
    save_project_yaml(
        "webtest",
        yaml_text + "workflow:\n  limits:\n    max_dev_retries: 4\n",
        root=tmp_path,
        create=False,
    )
    eff = effective_config_summary(project_id="webtest", root=tmp_path)
    assert eff["max_dev_retries"] == 4


def test_config_api_put_example():
    client = TestClient(app)
    r0 = client.get("/api/config/projects/_example")
    assert r0.status_code == 200
    original = r0.json()["yaml"]
    r1 = client.put(
        "/api/config/projects/_example",
        json={"yaml": original},
    )
    assert r1.status_code == 200
