"""M11–M13：内置默认流程、复制，以及项目里的角色模型。"""

import pytest
from fastapi.testclient import TestClient

from geni_studio.config.context import ConfigError
from geni_studio.config.registry import (
    apply_project_form,
    project_form_view,
    save_project_yaml,
)
from geni_studio.config.workflow_defs import (
    copy_workflow,
    get_workflow,
    list_workflows,
    save_workflow,
)
from geni_studio.web.app import app


def test_factory_default_is_listed_and_locked():
    found = [item for item in list_workflows() if item["workflow_id"] == "factory_default"]
    assert found and found[0]["builtin"] is True
    assert found[0]["engine"] == "default"
    loaded = get_workflow("factory_default")["workflow"]
    assert loaded["nodes"][0]["kind"] == "start"
    assert loaded["nodes"][-1]["kind"] == "end"
    with pytest.raises(ConfigError, match="先复制"):
        save_workflow("factory_default", loaded)


def test_copy_drops_the_builtin_flag(tmp_path):
    source = get_workflow("factory_default")["workflow"]
    root = tmp_path
    (root / "workflows" / "factory_default").mkdir(parents=True)
    from geni_studio.config.workflow_defs import _dump

    (root / "workflows" / "factory_default" / "workflow.yaml").write_text(
        _dump(source),
        encoding="utf-8",
    )
    (root / "roles").mkdir()
    for role in {node["role"] for node in source["nodes"] if node["kind"] == "activity"}:
        folder = root / "roles" / role
        folder.mkdir()
        (folder / "role.md").write_text("---\ntitle: 角色\n---\n", encoding="utf-8")
    copied = copy_workflow("factory_default", "copied_flow", "副本 · 默认流程", root=root)["workflow"]
    assert copied["workflow_id"] == "copied_flow"
    assert "builtin" not in copied
    assert "engine" not in copied
    assert len(copied["nodes"]) == len(source["nodes"])


def test_project_form_requires_a_real_workflow_and_stores_role_models(tmp_path, monkeypatch):
    monkeypatch.setattr("geni_studio.config.registry.factory_root", lambda: tmp_path)
    monkeypatch.setattr("geni_studio.config.workflow_defs.factory_root", lambda: tmp_path)
    (tmp_path / "scenarios" / "npu_operator").mkdir(parents=True)
    (tmp_path / "scenarios" / "npu_operator" / "scenario.yaml").write_text(
        "scenario_key: npu_operator\n",
        encoding="utf-8",
    )
    (tmp_path / "workflows" / "alpha").mkdir(parents=True)
    (tmp_path / "workflows" / "alpha" / "workflow.yaml").write_text(
        "workflow_id: alpha\ntitle: Alpha\nnodes:\n- {id: start, kind: start, name: 启动, role: human}\n- {id: end, kind: end, name: 结束, role: human}\n",
        encoding="utf-8",
    )
    save_project_yaml(
        "webtest",
        "project_id: webtest\ntitle: old\nscenario_key: npu_operator\n",
        root=tmp_path,
        create=True,
    )
    with pytest.raises(ConfigError, match="先选择流程"):
        apply_project_form(
            "webtest",
            {"title": "新标题", "profile_id": ""},
            root=tmp_path,
            require_profile=True,
        )
    text = apply_project_form(
        "webtest",
        {"title": "新标题", "profile_id": "alpha", "role_models": {"developer": "composer-2", "qa": ""}},
        root=tmp_path,
        require_profile=True,
    )
    assert "profile_id: alpha" in text
    assert "composer-2" in text
    assert project_form_view("webtest", tmp_path)["role_models"] == {"developer": "composer-2"}


def test_models_endpoint_uses_the_backend_list(monkeypatch):
    monkeypatch.setattr(
        "geni_studio.backends.models.list_backend_models",
        lambda: {"models": [{"id": "composer-2", "label": "Composer 2"}], "source": "cursor", "detail": ""},
    )
    # The route imports the function inside the handler, so patch the source module.
    body = TestClient(app).get("/api/config/models").json()
    assert body["models"][0]["id"] == "composer-2"


def test_project_page_requires_a_workflow_and_role_model_selects():
    page = TestClient(app).get("/project").text
    script = TestClient(app).get("/static/config.js").text
    assert 'id="fieldProfile"' in page
    assert 'waOption("", "不指定")' not in script
    assert "还没有流程。先创建一份。" in page
    assert 'id="region-models"' in page
    assert 'id="roleModelList"' in page
    assert 'id="fieldDirProfile"' in page
    assert ">所选流程</h2>" in page
    assert 'id="btnCopyFlow"' in page
