"""配置相关 REST API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from geni_studio.config.context import ConfigError
from geni_studio.config.identifiers import allocate_identifier
from geni_studio.config.registry import (
    apply_project_form,
    delete_project,
    describe_project_directory,
    effective_config_summary,
    get_project_yaml,
    get_scenario_yaml,
    list_directory_children,
    list_directory_entries,
    list_projects,
    list_scenarios,
    project_form_view,
    save_project_yaml,
    settings_status,
    template_file_error,
)
from geni_studio.web.errors import http_error

router = APIRouter(prefix="/api/config", tags=["config"])


class SaveProjectBody(BaseModel):
    yaml: str = Field(min_length=1)


class CreateProjectBody(BaseModel):
    project_id: str = ""
    title: str = ""
    yaml: str = ""


@router.get("/scenarios")
def api_list_scenarios() -> dict:
    items = [s.to_dict() for s in list_scenarios()]
    return {"scenarios": items}


@router.get("/scenarios/{scenario_key}")
def api_get_scenario(scenario_key: str) -> dict:
    try:
        text = get_scenario_yaml(scenario_key)
    except ConfigError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"scenario_key": scenario_key, "yaml": text, "readonly": True}


@router.get("/projects")
def api_list_projects() -> dict:
    from geni_studio.config.workflow_nodes import DEFAULT_GRAPH_NODES

    items = [p.to_dict() for p in list_projects()]
    return {"projects": items, "nodes": sorted(DEFAULT_GRAPH_NODES)}


@router.get("/projects/field-check")
def api_project_field_check(workspace: str = Query("")) -> dict:
    from geni_studio.workspace.layout import workspace_config_error

    errors: dict[str, str] = {}
    workspace_err = workspace_config_error(workspace.strip())
    if workspace_err:
        errors["workspace"] = workspace_err
    return {"ok": not errors, "errors": errors}


@router.get("/files")
def api_list_files(path: str = Query("")) -> dict:
    try:
        return list_directory_entries(path)
    except ConfigError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/files/check")
def api_check_template_file(path: str = Query("")) -> dict:
    message = template_file_error(path)
    if message:
        raise HTTPException(status_code=400, detail=message)
    return {"path": path.strip(), "ok": True}


@router.get("/directories")
def api_list_directories(path: str = Query("")) -> dict:
    try:
        return list_directory_children(path)
    except ConfigError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/projects/by-workspace")
def api_projects_by_workspace(path: str = Query("")) -> dict:
    try:
        return describe_project_directory(path)
    except ConfigError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/projects/{project_id}")
def api_get_project(project_id: str) -> dict:
    try:
        text = get_project_yaml(project_id)
    except ConfigError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"project_id": project_id, "yaml": text}


class ProjectFormBody(BaseModel):
    title: str = ""
    description: str = ""
    remote_url: str = ""
    scenario_key: str = ""
    profile_id: str = ""
    max_dev_retries: int | None = None
    design_track_mode: str = "inherit"
    skip_mode: str = "inherit"
    skip_nodes: list[str] = Field(default_factory=list)
    notify_chat_id: str = ""
    notify_open_id: str = ""
    workspace: str = ""
    role_models: dict[str, str] = Field(default_factory=dict)


@router.get("/projects/{project_id}/form")
def api_project_form(project_id: str) -> dict:
    try:
        return project_form_view(project_id)
    except ConfigError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.put("/projects/{project_id}/form")
def api_save_project_form(project_id: str, body: ProjectFormBody) -> dict:
    if body.design_track_mode not in {"inherit", "on", "off"}:
        raise HTTPException(status_code=400, detail="设计轨须为沿用、开启或关闭")
    if body.skip_mode not in {"inherit", "custom"}:
        raise HTTPException(status_code=400, detail="节点裁剪须为沿用项目类型或自行指定")
    try:
        text = apply_project_form(
            project_id,
            body.model_dump(exclude_unset=True),
            require_profile=True,
        )
    except ConfigError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail="重试次数须为整数") from e
    return {"project_id": project_id, "saved": True, "yaml": text}


@router.put("/projects/{project_id}")
def api_save_project(project_id: str, body: SaveProjectBody) -> dict:
    try:
        save_project_yaml(project_id, body.yaml, create=False)
    except ConfigError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"project_id": project_id, "saved": True}


@router.delete("/projects/{project_id}")
def api_delete_project(project_id: str) -> dict:
    try:
        delete_project(project_id)
    except ConfigError as e:
        raise http_error(e) from e
    return {"project_id": project_id, "deleted": True}


@router.post("/projects")
def api_create_project(body: CreateProjectBody) -> dict:
    project_id = body.project_id.strip()
    title = body.title.strip()
    if not project_id:
        if not title:
            raise HTTPException(status_code=400, detail="先写标题。")
        project_id = allocate_identifier(
            title,
            prefix="project",
            taken=[item.project_id for item in list_projects()],
        )
    yaml_text = body.yaml.strip()
    if not yaml_text:
        yaml_text = (
            f"project_id: {project_id}\n"
            f"title: {title or project_id}\n"
            "workflow:\n"
            "  profile_id: factory_default\n"
        )
    try:
        save_project_yaml(project_id, yaml_text, create=True)
    except ConfigError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"project_id": project_id, "created": True}


@router.get("/effective")
def api_effective_config(
    scenario_key: str = Query(""),
    project_id: str = Query(""),
) -> dict:
    try:
        return effective_config_summary(
            scenario_key=scenario_key,
            project_id=project_id,
        )
    except ConfigError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/models")
def api_models(backend: str = "") -> dict:
    from geni_studio.backends.models import list_backend_models

    return list_backend_models(backend=backend.strip() or None)


@router.get("/tools")
def api_tools(backend: str = "", project_id: str = "") -> dict:
    from geni_studio.backends.tools import list_backend_tools

    return list_backend_tools(backend=backend.strip() or None, project_id=project_id)


class RoleModelPrefBody(BaseModel):
    role: str = Field(min_length=1)
    backend: str = Field(min_length=1)
    model: str = ""
    effort: str = ""
    fast: str = ""
    params: dict[str, str] = Field(default_factory=dict)


@router.get("/user/role-model-prefs")
def api_role_model_prefs() -> dict:
    from geni_studio.config.user_prefs import role_model_prefs

    try:
        return {"role_model_prefs": role_model_prefs()}
    except ConfigError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.put("/user/role-model-prefs")
def api_set_role_model_pref(body: RoleModelPrefBody) -> dict:
    """记下一个角色在一个模型上的推理强度、Fast 与模型参数；全为默认时删去该项。"""
    from geni_studio.config.user_prefs import set_role_model_pref

    entry = {"effort": body.effort, "fast": body.fast, "params": body.params}
    try:
        prefs = set_role_model_pref(body.role, body.backend, body.model, entry)
    except ConfigError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except (TypeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"role_model_prefs": prefs}


class UiPrefBody(BaseModel):
    name: str = Field(min_length=1)
    value: str = ""


@router.get("/user/ui")
def api_ui_prefs() -> dict:
    from geni_studio.config.user_prefs import ui_prefs

    try:
        return {"ui": ui_prefs()}
    except ConfigError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.put("/user/ui")
def api_set_ui_pref(body: UiPrefBody) -> dict:
    from geni_studio.config.user_prefs import set_ui_pref

    try:
        return {"ui": set_ui_pref(body.name, body.value)}
    except ConfigError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.get("/settings")
def api_settings() -> dict:
    from geni_studio.config.env_loader import sync_env_secrets_to_dotenv

    sync_env_secrets_to_dotenv()
    return settings_status()


class SetSettingBody(BaseModel):
    key: str = Field(min_length=1)
    value: str = ""


@router.post("/settings")
def api_set_setting(body: SetSettingBody) -> dict:
    from geni_studio.cli import env_path, write_env_key
    from geni_studio.config.env_loader import apply_env_file

    try:
        write_env_key(env_path(), body.key, body.value)
    except SystemExit as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    apply_env_file(override=True)
    return settings_status()


@router.post("/settings/probe")
def api_probe_settings() -> dict:
    from geni_studio.config.connectivity import probe_saved_settings

    return probe_saved_settings()


class SaveSecretBody(BaseModel):
    key: str = Field(min_length=1)
    value: str = Field(min_length=1)


@router.post("/settings/secret")
def api_save_secret(body: SaveSecretBody) -> dict:
    """校验密钥后写入 .env；无效时不落盘。"""
    from geni_studio.cli import env_path, write_env_key
    from geni_studio.config.connectivity import validate_agent_secret
    from geni_studio.config.env_loader import apply_env_file, sync_env_secrets_to_dotenv

    ok, detail = validate_agent_secret(body.key, body.value)
    if not ok:
        raise HTTPException(status_code=400, detail=detail)
    try:
        write_env_key(env_path(), body.key, body.value.strip())
    except SystemExit as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    apply_env_file(override=True)
    sync_env_secrets_to_dotenv()
    return settings_status()
