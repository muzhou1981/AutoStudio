"""Web 配置 API 与 registry 测试。"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from geni_studio.config.context import ConfigError
from geni_studio.config.registry import (
    apply_project_form,
    delete_project,
    describe_project_directory,
    effective_config_summary,
    list_directory_children,
    list_projects,
    list_scenarios,
    project_form_view,
    save_project_yaml,
)
from geni_studio.web.app import app


def test_list_scenarios_and_projects():
    scenarios = list_scenarios()
    assert any(s.scenario_key == "npu_operator" for s in scenarios)
    projects = list_projects()
    assert any(p.project_id == "_example" for p in projects)


def test_effective_config_example_project(example_retry_limit):
    eff = effective_config_summary(project_id="_example")
    assert eff["scenario_key"] == "npu_operator"
    assert eff["max_dev_retries"] == example_retry_limit


def test_config_api_lists():
    client = TestClient(app)
    r = client.get("/api/config/scenarios")
    assert r.status_code == 200
    assert "npu_operator" in {x["scenario_key"] for x in r.json()["scenarios"]}
    r2 = client.get("/api/config/projects")
    assert r2.status_code == 200
    assert "_example" in {x["project_id"] for x in r2.json()["projects"]}


def test_delete_project_removes_directory(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("geni_studio.config.registry.factory_root", lambda: tmp_path)
    (tmp_path / "scenarios" / "npu_operator").mkdir(parents=True)
    (tmp_path / "scenarios" / "npu_operator" / "scenario.yaml").write_text(
        "scenario_key: npu_operator\n",
        encoding="utf-8",
    )
    (tmp_path / "projects").mkdir()
    save_project_yaml(
        "gone",
        "project_id: gone\ntitle: Gone\nscenario_key: npu_operator\n",
        root=tmp_path,
        create=True,
    )
    delete_project("gone", root=tmp_path)
    assert not (tmp_path / "projects" / "gone").exists()
    client = TestClient(app)
    still = client.post("/api/config/projects", json={"title": "api-del", "project_id": "api-del"})
    assert still.status_code == 200
    removed = client.delete("/api/config/projects/api-del")
    assert removed.status_code == 200
    assert removed.json()["deleted"] is True
    assert client.get("/api/config/projects/api-del").status_code == 404


def test_workspace_field_check_allows_factory_root(monkeypatch) -> None:
    from geni_studio.config.context import factory_root
    from geni_studio.workspace.layout import workspace_config_error

    assert workspace_config_error(str(factory_root())) is None


def test_project_field_check_api():
    client = TestClient(app)
    ok = client.get("/api/config/projects/field-check", params={"workspace": ""})
    assert ok.status_code == 200
    assert ok.json()["ok"] is True
    bad_ws = client.get(
        "/api/config/projects/field-check",
        params={"workspace": "/tmp"},
    )
    assert bad_ws.json()["ok"] is False
    assert "git" in bad_ws.json()["errors"]["workspace"]


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


def test_reasoning_setting_roundtrip_and_validation(tmp_path, monkeypatch):
    key = "GENI_STUDIO_CODEX_REASONING_EFFORT"
    monkeypatch.setenv(key, "")
    for module in ("config.registry", "cli", "config.env_loader"):
        monkeypatch.setattr(f"geni_studio.{module}.factory_root", lambda: tmp_path)
    client = TestClient(app)
    response = client.post("/api/config/settings", json={"key": key, "value": " HIGH "})
    assert response.status_code == 200
    row = next(x for x in response.json()["keys"] if x["name"] == key)
    assert row["configured"] is True
    assert row["value_hint"] == "high"
    assert (tmp_path / ".env").read_text() == f"{key}=high\n"
    rejected = client.post("/api/config/settings", json={"key": key, "value": "typo"})
    assert rejected.status_code == 400
    assert (tmp_path / ".env").read_text() == f"{key}=high\n"
    reset = client.post("/api/config/settings", json={"key": key, "value": "default"})
    assert reset.status_code == 200
    assert (tmp_path / ".env").read_text() == f"{key}=\n"
    row = next(x for x in reset.json()["keys"] if x["name"] == key)
    assert row["configured"] is False


def test_settings_suggests_open_id_when_env_empty(monkeypatch, tmp_path):
    from geni_studio.hitl.lark_cli_client import LarkCliAuthSummary

    monkeypatch.setattr("geni_studio.config.registry.factory_root", lambda: tmp_path)
    monkeypatch.setattr("geni_studio.cli.factory_root", lambda: tmp_path)
    monkeypatch.setattr("geni_studio.config.env_loader.factory_root", lambda: tmp_path)
    (tmp_path / ".env").write_text(
        "GENI_STUDIO_LARK_BACKEND=lark_cli\nGENI_STUDIO_FEISHU_NOTIFY_OPEN_ID=\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "geni_studio.hitl.lark_cli_client.auth_summary",
        lambda: LarkCliAuthSummary(
            True,
            True,
            True,
            "ok",
            user_open_id="ou_suggested",
            user_name="",
        ),
    )
    client = TestClient(app)
    row = next(
        k for k in client.get("/api/config/settings").json()["keys"]
        if k["name"] == "GENI_STUDIO_FEISHU_NOTIFY_OPEN_ID"
    )
    assert row["configured"] is False
    assert row["value_hint"] == "ou_suggested"
    assert row.get("suggested") is True


def test_settings_includes_lark_cli_user_open_id(monkeypatch):
    from geni_studio.hitl.lark_cli_client import LarkCliAuthSummary

    monkeypatch.setattr(
        "geni_studio.hitl.lark_cli_client.auth_summary",
        lambda: LarkCliAuthSummary(
            True,
            True,
            True,
            "ok",
            user_open_id="ou_from_cli",
            user_name="联调用户",
        ),
    )
    client = TestClient(app)
    lark = client.get("/api/config/settings").json()["lark_cli"]
    assert lark["user_open_id"] == "ou_from_cli"
    assert lark["user_name"] == "联调用户"


def test_settings_secret_reports_length_not_value(tmp_path, monkeypatch):
    monkeypatch.setattr("geni_studio.config.registry.factory_root", lambda: tmp_path)
    monkeypatch.setattr("geni_studio.cli.factory_root", lambda: tmp_path)
    monkeypatch.setattr("geni_studio.config.env_loader.factory_root", lambda: tmp_path)
    (tmp_path / ".env").write_text("CURSOR_API_KEY=abcdef\n", encoding="utf-8")
    from geni_studio.config.registry import settings_status

    body = settings_status(tmp_path)
    key = next(k for k in body["keys"] if k["name"] == "CURSOR_API_KEY")
    assert key["configured"] is True
    assert key["secret_length"] == 6
    assert "abcdef" not in json.dumps(body, ensure_ascii=False)


def test_save_secret_validates_before_persist(tmp_path, monkeypatch):
    import json as json_mod

    monkeypatch.setattr("geni_studio.config.registry.factory_root", lambda: tmp_path)
    monkeypatch.setattr("geni_studio.cli.factory_root", lambda: tmp_path)
    monkeypatch.setattr("geni_studio.config.env_loader.factory_root", lambda: tmp_path)
    monkeypatch.setattr(
        "geni_studio.config.connectivity.validate_agent_secret",
        lambda _key, _val: (True, "API Key 可用。"),
    )
    client = TestClient(app)
    bad = client.post(
        "/api/config/settings/secret",
        json={"key": "PATH", "value": "x"},
    )
    assert bad.status_code == 400
    ok = client.post(
        "/api/config/settings/secret",
        json={"key": "CURSOR_API_KEY", "value": "secret-value"},
    )
    assert ok.status_code == 200
    body = ok.json()
    key = next(k for k in body["keys"] if k["name"] == "CURSOR_API_KEY")
    assert key["configured"] is True
    assert key["secret_length"] == len("secret-value")
    assert "secret-value" not in json_mod.dumps(body)


def test_settings_cursor_key_from_environ_only(tmp_path, monkeypatch):
    monkeypatch.delenv("GENI_STUDIO_BACKEND", raising=False)
    monkeypatch.setattr("geni_studio.config.registry.factory_root", lambda: tmp_path)
    monkeypatch.setattr("geni_studio.config.env_loader.factory_root", lambda: tmp_path)
    (tmp_path / ".env").write_text("CURSOR_API_KEY=\n", encoding="utf-8")
    monkeypatch.setenv("CURSOR_API_KEY", "from-env")
    from geni_studio.config.registry import settings_status

    body = settings_status(tmp_path)
    assert body["effective_backend"] == "cursor"
    key = next(k for k in body["keys"] if k["name"] == "CURSOR_API_KEY")
    assert key["configured"] is True


def test_config_page_and_static():
    client = TestClient(app)
    page = client.get("/config")
    assert page.status_code == 200
    assert "原文 project.yaml" not in page.text
    assert 'id="projectRaw"' not in page.text
    assert 'id="projectYaml"' not in page.text
    assert 'id="btnSaveRaw"' not in page.text
    assert "原文 workflow.yaml" in page.text
    assert "原文 JSON" in page.text
    assert client.get("/static/shared.css").status_code == 200


def test_save_project_tmp_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "geni_studio.config.registry.factory_root",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        "geni_studio.config.context.factory_root",
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


def test_api_form_save_preserves_remote_url_when_omitted(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("geni_studio.config.registry.factory_root", lambda: tmp_path)
    monkeypatch.setattr("geni_studio.config.workflow_defs.factory_root", lambda: tmp_path)
    (tmp_path / "scenarios" / "npu_operator").mkdir(parents=True)
    (tmp_path / "scenarios" / "npu_operator" / "scenario.yaml").write_text(
        "scenario_key: npu_operator\n",
        encoding="utf-8",
    )
    (tmp_path / "workflows" / "alpha").mkdir(parents=True)
    (tmp_path / "workflows" / "alpha" / "workflow.yaml").write_text(
        "workflow_id: alpha\ntitle: Alpha\nnodes:\n- {id: start, kind: start, name: 启动, role: human}\n",
        encoding="utf-8",
    )
    save_project_yaml(
        "keep-remote",
        "project_id: keep-remote\ntitle: T\nremote_url: https://github.com/org/r.git\n"
        "scenario_key: npu_operator\n",
        root=tmp_path,
        create=True,
    )
    client = TestClient(app)
    payload = {
        "title": "T2",
        "description": "",
        "scenario_key": "npu_operator",
        "profile_id": "alpha",
        "max_dev_retries": None,
        "design_track_mode": "inherit",
        "skip_mode": "inherit",
        "skip_nodes": [],
        "notify_chat_id": "",
        "notify_open_id": "",
        "workspace": "",
    }
    r = client.put("/api/config/projects/keep-remote/form", json=payload)
    assert r.status_code == 200
    view = project_form_view("keep-remote", tmp_path)
    assert view["title"] == "T2"
    assert view["remote_url"] == "https://github.com/org/r.git"


def test_project_page_workspace_follows_description():
    client = TestClient(app)
    page = client.get("/project").text
    description = page.index('id="fieldDescription"')
    workspace = page.index('id="fieldWorkspace"')
    assert description < workspace
    assert 'id="fieldRemoteUrl"' not in page
    assert "原文 project.yaml" not in page
    assert 'id="projectYaml"' not in page
    assert 'id="btnSaveRaw"' not in page
    assert 'aria-label="选择工作区目录"' in page
    assert 'id="btnClearWorkspace"' in page
    assert "待开发项目的 git 目录，可空" in page
    assert "原文 workflow.yaml" in page
    css = client.get("/static/hitl.css").text
    row = css.split(".workspace-pick-row {", 1)[1].split("}", 1)[0]
    assert "align-items: flex-end" in row
    assert "align-self: flex-end" not in css.split(".workspace-pick-row #btnClearWorkspace {", 1)[1].split("}", 1)[0]
    assert "markFormDirty" not in client.get("/static/config.js").text


def test_project_workspace_overrides_default_root(tmp_path, monkeypatch):
    from geni_studio.workspace.layout import resolve_target_root

    monkeypatch.setattr("geni_studio.config.registry.factory_root", lambda: tmp_path)
    monkeypatch.setattr("geni_studio.workspace.layout.factory_root", lambda: tmp_path)
    monkeypatch.setenv("GENI_STUDIO_TARGET_ROOT", str(tmp_path / "from-env"))
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


def test_settings_rejects_non_open_id_for_feishu_notify(tmp_path, monkeypatch):
    monkeypatch.setattr("geni_studio.config.registry.factory_root", lambda: tmp_path)
    monkeypatch.setattr("geni_studio.cli.factory_root", lambda: tmp_path)
    monkeypatch.setattr("geni_studio.config.env_loader.factory_root", lambda: tmp_path)
    client = TestClient(app)
    r = client.post(
        "/api/config/settings",
        json={"key": "GENI_STUDIO_FEISHU_NOTIFY_OPEN_ID", "value": "cursor"},
    )
    assert r.status_code == 400
    assert "ou_" in r.json()["detail"]


def test_web_sets_backend_and_masks_api_key(tmp_path, monkeypatch):
    monkeypatch.setattr("geni_studio.config.registry.factory_root", lambda: tmp_path)
    monkeypatch.setattr("geni_studio.cli.factory_root", lambda: tmp_path)
    monkeypatch.setattr("geni_studio.config.env_loader.factory_root", lambda: tmp_path)
    client = TestClient(app)
    r = client.post(
        "/api/config/settings",
        json={"key": "GENI_STUDIO_BACKEND", "value": "cursor"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["effective_backend"] == "cursor"
    backend = next(k for k in body["keys"] if k["name"] == "GENI_STUDIO_BACKEND")
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
    hint = next(k for k in implied.json()["keys"] if k["name"] == "GENI_STUDIO_BACKEND")
    assert hint["value_hint"] == "cursor"  # 当前进程仍显式选择 cursor。


def _ready_lark(monkeypatch: pytest.MonkeyPatch) -> None:
    from geni_studio.hitl.lark_cli_client import LarkCliAuthSummary

    monkeypatch.setattr(
        "geni_studio.hitl.lark_cli_client.auth_summary",
        lambda: LarkCliAuthSummary(True, True, True, "ok"),
    )


def test_probe_cursor_skips_when_verify_disabled(monkeypatch):
    monkeypatch.setenv("GENI_STUDIO_CURSOR_VERIFY", "0")
    monkeypatch.setenv("GENI_STUDIO_BACKEND", "cursor")
    monkeypatch.setenv("CURSOR_API_KEY", "test-key")
    from geni_studio.config.connectivity import probe_saved_settings

    body = probe_saved_settings()
    agent = next(item for item in body["checks"] if item["name"] == "Agent")
    assert agent["status"] == "ok"
    assert "跳过" in agent["detail"]


def test_probe_reports_connected_for_stub(monkeypatch, tmp_path):
    _ready_lark(monkeypatch)
    monkeypatch.setenv("GENI_STUDIO_LARK_BACKEND", "lark_cli")
    monkeypatch.setenv("GENI_STUDIO_TARGET_ROOT", str(tmp_path))
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


def test_probe_reports_missing_cursor_key(monkeypatch):
    from geni_studio.config.connectivity import probe_saved_settings

    _ready_lark(monkeypatch)
    monkeypatch.setenv("GENI_STUDIO_BACKEND", "cursor")
    monkeypatch.setenv("GENI_STUDIO_LARK_BACKEND", "lark_cli")
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    body = probe_saved_settings()
    assert body["ok"] is False
    agent = next(item for item in body["checks"] if item["name"] == "Agent")
    assert agent["status"] == "fail"
    assert "未配置" in agent["detail"]


def test_probe_cursor_failure_does_not_echo_the_key(monkeypatch):
    import os

    from geni_studio.config.connectivity import probe_saved_settings

    _ready_lark(monkeypatch)
    monkeypatch.setenv("GENI_STUDIO_BACKEND", "cursor")
    monkeypatch.setenv("GENI_STUDIO_LARK_BACKEND", "lark_cli")
    monkeypatch.setenv("CURSOR_API_KEY", "secret-value")

    def fail_key(api_key, model):
        return ("fail", "API Key 无效。到 Cursor 设置里更新 User API Key，再写入一次。")

    monkeypatch.setattr("geni_studio.config.connectivity.probe_cursor_key", fail_key)
    body = probe_saved_settings()
    assert body["ok"] is False
    assert body["summary"].startswith("连不上。")
    assert "secret-value" not in body["summary"]
    assert os.environ.get("CURSOR_API_KEY") == "secret-value"
