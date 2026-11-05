"""配置相关 REST API。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from auto_studio.config.context import ConfigError
from auto_studio.config.registry import (
    effective_config_summary,
    get_project_yaml,
    get_scenario_yaml,
    list_projects,
    list_scenarios,
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
