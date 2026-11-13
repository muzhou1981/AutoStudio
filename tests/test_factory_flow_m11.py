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
    delete_workflow,
    get_workflow,
    list_workflows,
    save_workflow,
)
from geni_studio.web.app import app


def test_activity_roles_include_nested_workflows(tmp_path):
    for role_id, title in (("architect", "架构师"), ("developer", "程序员")):
        folder = tmp_path / "roles" / role_id
        folder.mkdir(parents=True)
        (folder / "role.md").write_text(f"---\ntitle: {title}\n---\n", encoding="utf-8")
    child = tmp_path / "workflows" / "child"
    child.mkdir(parents=True)
    (child / "workflow.yaml").write_text(
        "workflow_id: child\ntitle: 子\nsubgraph: true\nnodes:\n"
        "- {id: start, kind: start, name: 启动, role: human}\n"
        "- {id: work, kind: activity, name: 实现, role: developer}\n"
        "- {id: end, kind: end, name: 结束, role: human}\n",
        encoding="utf-8",
    )
    parent = tmp_path / "workflows" / "parent"
    parent.mkdir()
    (parent / "workflow.yaml").write_text(
        "workflow_id: parent\ntitle: 父\nnodes:\n"
        "- {id: start, kind: start, name: 启动, role: human}\n"
        "- {id: plan, kind: activity, name: 合同, role: architect}\n"
        "- {id: path, kind: subgraph, name: 子流程, role: '', subgraph_id: child}\n"
        "- {id: end, kind: end, name: 结束, role: human}\n",
        encoding="utf-8",
    )
    from geni_studio.config.workflow_defs import workflow_activity_roles

    roles = workflow_activity_roles("parent", tmp_path)
    assert [item["id"] for item in roles] == ["architect", "developer"]
    assert roles[0]["label"] == "架构师"


def test_factory_default_is_listed_and_locked():
    found = [item for item in list_workflows() if item["workflow_id"] == "factory_default"]
    assert found and found[0]["builtin"] is True
    assert found[0]["title"] == "通用软件开发"
    assert "engine" not in found[0]
    loaded = get_workflow("factory_default")["workflow"]
    assert "engine" not in loaded
    assert {node["kind"] for node in loaded["nodes"][1:-1]} == {"activity", "system", "gate"}
    systems = [node for node in loaded["nodes"] if node["kind"] == "system"]
    assert all(node["handler"] in {"pm_clarification_check", "hitl_pause", "config_manager_plan",
                                   "project_manager_scope", "change_control", "escalate_dev_retry"} for node in systems)
    assert loaded["nodes"][0]["kind"] == "start"
    assert loaded["nodes"][-1]["kind"] == "end"
    with pytest.raises(ConfigError, match="先复制"):
        save_workflow("factory_default", loaded)
    assert found[0]["hidden"] is True
    assert not any(item["hidden"] for item in list_workflows() if item["workflow_id"] != "factory_default")


def test_hidden_workflow_cannot_be_newly_chosen_but_stays_for_existing_projects(tmp_path, monkeypatch):
    monkeypatch.setattr("geni_studio.config.registry.factory_root", lambda: tmp_path)
    monkeypatch.setattr("geni_studio.config.workflow_defs.factory_root", lambda: tmp_path)
    for flow_id, extra in (("old", "hidden: true\n"), ("alpha", "")):
        (tmp_path / "workflows" / flow_id).mkdir(parents=True)
        (tmp_path / "workflows" / flow_id / "workflow.yaml").write_text(
            f"workflow_id: {flow_id}\ntitle: {flow_id}\n{extra}nodes:\n"
            "- {id: start, kind: start, name: 启动, role: human}\n- {id: end, kind: end, name: 结束, role: human}\n",
            encoding="utf-8",
        )
    save_project_yaml("fresh", "project_id: fresh\ntitle: fresh\n", root=tmp_path, create=True)
    with pytest.raises(ConfigError, match="停止选用"):
        apply_project_form("fresh", {"title": "fresh", "profile_id": "old"}, root=tmp_path, require_profile=True)
    save_project_yaml(
        "legacy", "project_id: legacy\ntitle: legacy\nworkflow:\n  profile_id: old\n", root=tmp_path, create=True
    )
    text = apply_project_form("legacy", {"title": "改名", "profile_id": "old"}, root=tmp_path, require_profile=True)
    assert "profile_id: old" in text
    assert "profile_id: alpha" in apply_project_form(
        "legacy", {"title": "改名", "profile_id": "alpha"}, root=tmp_path, require_profile=True
    )


def test_self_improve_is_builtin_and_executable():
    from geni_studio.workflows.executable import resolve_executable

    found = [item for item in list_workflows() if item["workflow_id"] == "self_improve"]
    assert found and found[0]["builtin"] is True
    assert found[0]["title"] == "自我改进"
    loaded = get_workflow("self_improve")["workflow"]
    prepared = resolve_executable(loaded)
    names = [node["name"] for node in prepared["nodes"]]
    assert names == ["启动", "听清改动", "确认改动", "改代码", "自行核对", "看结果", "写交付说明", "确认入库", "提交入库", "结束"]
    assert loaded["workspace"] == "current_branch"
    land = next(node for node in prepared["nodes"] if node["id"] == "land_commit")
    assert land["role"] == "developer"
    assert land["commits_on_branch"] is True
    assert land["outputs"] == ["land_record"]
    assert land["on_current_branch"] is True
    hear = next(node for node in prepared["nodes"] if node["id"] == "hear")
    assert hear["outputs"] == ["requirement_spec"]
    change = next(node for node in prepared["nodes"] if node["id"] == "change_code")
    assert change["outputs"] == ["code_change"]
    check = next(node for node in prepared["nodes"] if node["id"] == "self_check")
    assert check["outputs"] == ["test_report"]
    assert check["returns_to"] == "change_code"
    assert check["max_loops"] == 3
    handoff = next(node for node in prepared["nodes"] if node["id"] == "handoff")
    assert handoff["outputs"] == ["delivery_report"]
    review = next(node for node in prepared["nodes"] if node["id"] == "review")
    assert review["reject_to"] == "change_code"

    with pytest.raises(ConfigError, match="先复制"):
        save_workflow("self_improve", loaded)
    with pytest.raises(ConfigError, match="不能删除"):
        delete_workflow("self_improve")
    assert get_workflow("self_improve")["workflow"]["workflow_id"] == "self_improve"


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
        lambda *, backend=None: {
            "models": [{"id": "composer-2", "label": "Composer 2"}],
            "source": "cursor" if backend == "cursor" else "stub",
            "detail": "",
        },
    )
    # The route imports the function inside the handler, so patch the source module.
    body = TestClient(app).get("/api/config/models?backend=cursor").json()
    assert body["models"][0]["id"] == "composer-2"


def test_project_page_requires_a_workflow_and_role_model_selects():
    page = TestClient(app).get("/project").text
    script = TestClient(app).get("/static/config.js").text
    assert 'id="fieldProfile"' in page
    assert 'waOption("", "不指定")' not in script
    assert "还没有流程。先创建一份。" in page
    assert 'id="region-models"' not in page
    assert 'id="runRoleModels"' not in page
    assert 'id="fieldDirProfile"' in page
    assert ">所选流程</h2>" in page
    assert 'id="btnCopyFlow"' not in page and 'id="flowRenameForm"' not in page
    assert 'id="flowNameEdit"' in page and 'id="btnNameSave" variant="brand" hidden>保存</wa-button>' in page
    flow_script = TestClient(app).get("/static/workflow.js").text
    assert 'rows.push({ title: "复制为新流程", onPick: () => openNameEdit("copy") });' in flow_script
    assert 'if (!builtin) rows.push({ title: "重命名……", onPick: () => openNameEdit("rename") });' in flow_script
    assert "body: JSON.stringify(wire({ ...savedGraph, title }))," in flow_script
