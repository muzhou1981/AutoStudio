"""配置相关 REST API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from auto_studio.config.context import ConfigError
from auto_studio.config.registry import (
    apply_project_form,
    effective_config_summary,
    get_project_yaml,
    get_scenario_yaml,
    list_projects,
    list_scenarios,
    project_form_view,
    save_project_yaml,
    settings_status,
)

router = APIRouter(prefix="/api/config", tags=["config"])


class SaveProjectBody(BaseModel):
    yaml: str = Field(min_length=1)


class CreateProjectBody(BaseModel):
    project_id: str = Field(min_length=1)
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
    items = [p.to_dict() for p in list_projects()]
    return {"projects": items}


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
    scenario_key: str = ""
    profile_id: str = ""
    max_dev_retries: int | None = None
    design_track_mode: str = "inherit"
    skip_mode: str = "inherit"
    skip_nodes: list[str] = Field(default_factory=list)
    notify_chat_id: str = ""
    notify_open_id: str = ""
    workspace: str = ""


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
        raise HTTPException(status_code=400, detail="节点裁剪须为沿用场景或自行指定")
    try:
        text = apply_project_form(project_id, body.model_dump())
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


@router.post("/projects")
def api_create_project(body: CreateProjectBody) -> dict:
    yaml_text = body.yaml.strip()
    if not yaml_text:
        yaml_text = (
            f"project_id: {body.project_id}\n"
            f"title: {body.project_id}\n"
            f"scenario_key: npu_operator\n"
        )
    try:
        save_project_yaml(body.project_id, yaml_text, create=True)
    except ConfigError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"project_id": body.project_id, "created": True}


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


@router.get("/settings")
def api_settings() -> dict:
    return settings_status()


class SetSettingBody(BaseModel):
    key: str = Field(min_length=1)
    value: str = ""


@router.post("/settings")
def api_set_setting(body: SetSettingBody) -> dict:
    from auto_studio.cli import env_path, write_env_key
    from auto_studio.config.env_loader import apply_env_file

    try:
        write_env_key(env_path(), body.key, body.value)
    except SystemExit as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    apply_env_file(override=True)
    return settings_status()


@router.post("/settings/probe")
def api_probe_settings() -> dict:
    from auto_studio.config.connectivity import probe_saved_settings

    return probe_saved_settings()
