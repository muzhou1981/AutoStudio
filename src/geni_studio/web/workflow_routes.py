"""流程定义的读写接口。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from geni_studio.config.context import ConfigError
from geni_studio.config.identifiers import allocate_identifier
from geni_studio.config.workflow_defs import (
    copy_workflow,
    create_workflow,
    get_workflow,
    import_workflow,
    list_role_lanes,
    list_workflows,
    save_as_subgraph,
    save_workflow,
    save_workflow_yaml,
    workflow_activity_roles,
)

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


class CreateWorkflowBody(BaseModel):
    workflow_id: str = ""
    title: str = ""


class SaveWorkflowBody(BaseModel):
    workflow_id: str = ""
    title: str = ""
    description: str = ""
    subgraph: bool = False
    nodes: list[dict[str, Any]] = Field(default_factory=list)


class SaveWorkflowYamlBody(BaseModel):
    yaml: str = ""


class ImportWorkflowBody(BaseModel):
    yaml: str = ""


class CopyWorkflowBody(BaseModel):
    title: str = ""


class SaveSubgraphBody(BaseModel):
    title: str = ""
    description: str = ""
    nodes: list[dict[str, Any]] = Field(default_factory=list)


def _http(exc: ConfigError) -> HTTPException:
    missing = str(exc).startswith("流程不存在")
    return HTTPException(status_code=404 if missing else 400, detail=str(exc))


@router.get("")
def api_list_workflows() -> dict:
    return {"workflows": list_workflows()}


@router.get("/roles")
def api_list_roles() -> dict:
    return {"roles": list_role_lanes()}


@router.post("")
def api_create_workflow(body: CreateWorkflowBody) -> dict:
    workflow_id = body.workflow_id.strip()
    title = body.title.strip()
    if not workflow_id:
        if not title:
            raise HTTPException(status_code=400, detail="先写标题。")
        workflow_id = allocate_identifier(
            title,
            prefix="workflow",
            taken=[item["workflow_id"] for item in list_workflows()],
        )
    try:
        return create_workflow(workflow_id, title or workflow_id)
    except ConfigError as exc:
        raise _http(exc) from exc


@router.post("/import")
def api_import_workflow(body: ImportWorkflowBody) -> dict:
    try:
        return import_workflow(body.yaml)
    except ConfigError as exc:
        raise _http(exc) from exc


@router.post("/{workflow_id}/as-subgraph")
def api_save_as_subgraph(workflow_id: str, body: SaveSubgraphBody) -> dict:
    try:
        get_workflow(workflow_id)
    except ConfigError as exc:
        raise _http(exc) from exc
    try:
        return save_as_subgraph(body.title, body.nodes, body.description)
    except ConfigError as exc:
        raise _http(exc) from exc


@router.post("/{workflow_id}/copy")
def api_copy_workflow(workflow_id: str, body: CopyWorkflowBody) -> dict:
    try:
        source = get_workflow(workflow_id)["workflow"]
    except ConfigError as exc:
        raise _http(exc) from exc
    title = body.title.strip() or ("副本 · " + str(source.get("title") or workflow_id))
    new_id = allocate_identifier(
        title,
        prefix="workflow",
        taken=[item["workflow_id"] for item in list_workflows()],
    )
    try:
        return copy_workflow(workflow_id, new_id, title)
    except ConfigError as exc:
        raise _http(exc) from exc


@router.get("/{workflow_id}/activity-roles")
def api_workflow_activity_roles(workflow_id: str) -> dict:
    try:
        return {"roles": workflow_activity_roles(workflow_id)}
    except ConfigError as exc:
        raise _http(exc) from exc


@router.get("/{workflow_id}")
def api_get_workflow(workflow_id: str) -> dict:
    try:
        return get_workflow(workflow_id)
    except ConfigError as exc:
        raise _http(exc) from exc


@router.put("/{workflow_id}")
def api_save_workflow(workflow_id: str, body: SaveWorkflowBody) -> dict:
    try:
        return save_workflow(workflow_id, body.model_dump())
    except ConfigError as exc:
        raise _http(exc) from exc


@router.put("/{workflow_id}/raw")
def api_save_workflow_yaml(workflow_id: str, body: SaveWorkflowYamlBody) -> dict:
    try:
        return save_workflow_yaml(workflow_id, body.yaml)
    except ConfigError as exc:
        raise _http(exc) from exc
