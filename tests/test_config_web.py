"""Web 配置 API 与 registry 测试。"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from auto_studio.config.context import ConfigError
from auto_studio.config.registry import (
    apply_project_form,
    describe_project_directory,
    effective_config_summary,
    list_directory_children,
    list_projects,
    list_scenarios,
    project_form_view,
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


def test_describe_project_directory_matches_workspace(tmp_path: Path) -> None:
    import subprocess

    repo = tmp_path / "widget"
    repo.mkdir()
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    proj = tmp_path / "projects" / "widget"
    proj.mkdir(parents=True)
    (proj / "project.yaml").write_text(
        "project_id: widget\ntitle: Widget\nscenario_key: npu_operator\nworkspace: "
        + str(repo)
        + "\n",
        encoding="utf-8",
    )
    found = describe_project_directory(str(repo), root=tmp_path)
    assert found["project_ids"] == ["widget"]
    assert found["suggested_id"] == "widget"
    assert found["remote_url"] == ""
    subprocess.run(
        ["git", "-C", str(repo), "remote", "add", "origin", "https://github.com/org/widget.git"],
        check=True,
        capture_output=True,
    )
    with_remote = describe_project_directory(str(repo), root=tmp_path)
    assert with_remote["remote_url"] == "https://github.com/org/widget.git"
    with pytest.raises(ConfigError, match="目录不存在"):
        describe_project_directory(str(tmp_path / "missing"), root=tmp_path)


def test_list_directory_children_lists_dirs_only(tmp_path: Path) -> None:
    (tmp_path / "b-dir").mkdir()
    (tmp_path / "a-dir").mkdir()
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "note.txt").write_text("x", encoding="utf-8")
    found = list_directory_children(str(tmp_path))
    assert found["path"] == str(tmp_path.resolve())
    assert [item["name"] for item in found["dirs"]] == ["a-dir", "b-dir", ".hidden"]
    assert found["parent"] == str(tmp_path.resolve().parent)
    with pytest.raises(ConfigError, match="目录不存在"):
        list_directory_children(str(tmp_path / "missing"))
    note = tmp_path / "note.txt"
    with pytest.raises(ConfigError, match="不能是文件"):
        list_directory_children(str(note))
    client = TestClient(app)
    response = client.get("/api/config/directories", params={"path": str(tmp_path)})
    assert response.status_code == 200
    assert response.json()["dirs"][0]["name"] == "a-dir"


def test_config_api_settings():
    client = TestClient(app)
    r = client.get("/api/config/settings")
    assert r.status_code == 200
    assert "keys" in r.json()


def test_config_page_and_static():
    client = TestClient(app)
    page = client.get("/config")
    assert page.status_code == 200
    assert "原文 project.yaml" in page.text
    assert "原文 JSON" in page.text
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


def test_apply_project_form_preserves_extra(tmp_path):
    (tmp_path / "scenarios" / "npu_operator").mkdir(parents=True)
    (tmp_path / "scenarios" / "npu_operator" / "scenario.yaml").write_text(
        "scenario_key: npu_operator\n",
        encoding="utf-8",
    )
    save_project_yaml(
        "webtest",
        "project_id: webtest\ntitle: old\nscenario_key: npu_operator\nnote: keep-me\n",
        root=tmp_path,
        create=True,
    )
    text = apply_project_form(
        "webtest",
        {
            "title": "新标题",
            "description": "一行说明",
            "scenario_key": "npu_operator",
            "profile_id": "",
            "max_dev_retries": 4,
            "design_track_mode": "off",
            "skip_mode": "inherit",
            "skip_nodes": [],
            "notify_chat_id": "oc_demo",
            "notify_open_id": "",
        },
        root=tmp_path,
    )
    assert "keep-me" in text
    view = project_form_view("webtest", tmp_path)
    assert view["title"] == "新标题"
    assert view["max_dev_retries"] == 4
    assert view["design_track_mode"] == "off"
    assert view["notify_chat_id"] == "oc_demo"
    assert view["skip_mode"] == "inherit"
    assert view["workspace"] == ""


def test_project_remote_url_roundtrip_and_rejects_a_path(tmp_path):
    (tmp_path / "scenarios" / "npu_operator").mkdir(parents=True)
    (tmp_path / "scenarios" / "npu_operator" / "scenario.yaml").write_text(
        "scenario_key: npu_operator\n",
        encoding="utf-8",
    )
    save_project_yaml(
        "webtest",
        "project_id: webtest\ntitle: old\nscenario_key: npu_operator\n",
        root=tmp_path,
        create=True,
    )
    url = "https://github.com/org/repo.git"
    text = apply_project_form(
        "webtest",
        {"title": "新标题", "scenario_key": "npu_operator", "remote_url": url},
        root=tmp_path,
    )
    assert f"remote_url: {url}" in text
    assert project_form_view("webtest", tmp_path)["remote_url"] == url
    text = apply_project_form(
        "webtest",
        {"title": "新标题", "scenario_key": "npu_operator", "remote_url": "git@github.com:org/repo.git"},
        root=tmp_path,
    )
    assert "git@github.com:org/repo.git" in text
    with pytest.raises(ConfigError, match="git 地址"):
        apply_project_form(
            "webtest",
            {"title": "新标题", "scenario_key": "npu_operator", "remote_url": "/tmp/repo"},
            root=tmp_path,
        )
    cleared = apply_project_form(
        "webtest",
        {"title": "新标题", "scenario_key": "npu_operator", "remote_url": ""},
        root=tmp_path,
    )
    assert "remote_url" not in cleared
    assert project_form_view("webtest", tmp_path)["remote_url"] == ""


def test_project_page_puts_remote_url_between_description_and_workspace():
    page = TestClient(app).get("/project").text
    description = page.index('id="fieldDescription"')
    remote = page.index('id="fieldRemoteUrl"')
    workspace = page.index('id="fieldWorkspace"')
    assert description < remote < workspace
    assert 'label="远程仓库"' in page


def test_project_workspace_overrides_default_root(tmp_path, monkeypatch):
    from auto_studio.workspace.layout import resolve_target_root

    monkeypatch.setattr("auto_studio.config.registry.factory_root", lambda: tmp_path)
    monkeypatch.setattr("auto_studio.workspace.layout.factory_root", lambda: tmp_path)
    monkeypatch.setenv("AUTO_STUDIO_TARGET_ROOT", str(tmp_path / "from-env"))
    (tmp_path / "scenarios" / "npu_operator").mkdir(parents=True)
    (tmp_path / "scenarios" / "npu_operator" / "scenario.yaml").write_text(
        "scenario_key: npu_operator\n",
        encoding="utf-8",
    )
    repo = tmp_path / "app-repo"
    repo.mkdir()
    save_project_yaml(
        "webtest",
        "project_id: webtest\ntitle: old\nscenario_key: npu_operator\n",
        root=tmp_path,
        create=True,
    )
    text = apply_project_form(
        "webtest",
        {
            "title": "新标题",
            "scenario_key": "npu_operator",
            "workspace": str(repo),
        },
        root=tmp_path,
    )
    assert f"workspace: {repo}" in text
    view = project_form_view("webtest", tmp_path)
    assert view["workspace"] == str(repo)
    assert Path(view["workspace_resolved"]) == repo.resolve()
    assert resolve_target_root("webtest") == repo.resolve()

    occupied = tmp_path / "not-a-repo"
    occupied.mkdir()
    (occupied / "readme.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ValueError, match="git 仓库"):
        apply_project_form(
            "webtest",
            {"title": "新标题", "scenario_key": "npu_operator", "workspace": str(occupied)},
            root=tmp_path,
        )


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


def test_web_sets_backend_and_masks_api_key(tmp_path, monkeypatch):
    monkeypatch.setattr("auto_studio.config.registry.factory_root", lambda: tmp_path)
    monkeypatch.setattr("auto_studio.cli.factory_root", lambda: tmp_path)
    monkeypatch.setattr("auto_studio.config.env_loader.factory_root", lambda: tmp_path)
    client = TestClient(app)
    r = client.post(
        "/api/config/settings",
        json={"key": "AUTO_STUDIO_BACKEND", "value": "cursor"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["effective_backend"] == "cursor"
    backend = next(k for k in body["keys"] if k["name"] == "AUTO_STUDIO_BACKEND")
    assert backend["value_hint"] == "cursor"
    r2 = client.post(
        "/api/config/settings",
        json={"key": "CURSOR_API_KEY", "value": "secret-value"},
    )
    assert r2.status_code == 200
    text = r2.text
    assert "secret-value" not in text
    key = next(k for k in r2.json()["keys"] if k["name"] == "CURSOR_API_KEY")
    assert key["configured"] is True
    assert key["value_hint"] == "已设置"
    assert "CURSOR_API_KEY=secret-value" in (tmp_path / ".env").read_text(encoding="utf-8")
    bad = client.post("/api/config/settings", json={"key": "PATH", "value": "/tmp"})
    assert bad.status_code == 400
    (tmp_path / ".env").write_text("CURSOR_API_KEY=secret-value\n", encoding="utf-8")
    implied = client.get("/api/config/settings")
    assert implied.status_code == 200
    assert implied.json()["effective_backend"] == "cursor"
    assert "secret-value" not in implied.text
    hint = next(k for k in implied.json()["keys"] if k["name"] == "AUTO_STUDIO_BACKEND")
    assert "当前生效 cursor" in hint["value_hint"]


def _ready_lark(monkeypatch: pytest.MonkeyPatch) -> None:
    from auto_studio.hitl.lark_cli_client import LarkCliAuthSummary

    monkeypatch.setattr(
        "auto_studio.hitl.lark_cli_client.auth_summary",
        lambda: LarkCliAuthSummary(True, True, True, "ok"),
    )


def test_probe_reports_connected_for_stub(monkeypatch, tmp_path):
    _ready_lark(monkeypatch)
    monkeypatch.setenv("AUTO_STUDIO_LARK_BACKEND", "lark_cli")
    monkeypatch.setenv("AUTO_STUDIO_TARGET_ROOT", str(tmp_path))
    client = TestClient(app)
    probed = client.post("/api/config/settings/probe")
    assert probed.status_code == 200
    body = probed.json()
    assert body["ok"] is True
    assert body["summary"] == "已连通。"
    names = {item["name"]: item["status"] for item in body["checks"]}
    assert names["Agent"] == "ok"
    assert names["默认工作区"] == "ok"
    assert names["飞书"] == "ok"


def test_probe_skips_missing_cursor_key_and_keeps_saved_value(monkeypatch):
    from auto_studio.config.connectivity import probe_saved_settings

    _ready_lark(monkeypatch)
    monkeypatch.setenv("AUTO_STUDIO_BACKEND", "cursor")
    monkeypatch.setenv("AUTO_STUDIO_LARK_BACKEND", "lark_cli")
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    body = probe_saved_settings()
    assert body["ok"] is True
    agent = next(item for item in body["checks"] if item["name"] == "Agent")
    assert agent["status"] == "skip"
    assert "未配置" in agent["detail"]


def test_probe_cursor_failure_does_not_echo_the_key(monkeypatch):
    import os

    from auto_studio.config.connectivity import probe_saved_settings

    _ready_lark(monkeypatch)
    monkeypatch.setenv("AUTO_STUDIO_BACKEND", "cursor")
    monkeypatch.setenv("AUTO_STUDIO_LARK_BACKEND", "lark_cli")
    monkeypatch.setenv("CURSOR_API_KEY", "secret-value")

    def fail_key(api_key, model):
        return ("fail", "API Key 无效。到 Cursor 设置里更新 User API Key，再写入一次。")

    monkeypatch.setattr("auto_studio.config.connectivity.probe_cursor_key", fail_key)
    body = probe_saved_settings()
    assert body["ok"] is False
    assert body["summary"].startswith("连不上。")
    assert "secret-value" not in body["summary"]
    assert os.environ.get("CURSOR_API_KEY") == "secret-value"
