"""流程定义的读写接口。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from geni_studio.config.context import ConfigError, factory_root
from geni_studio.config.identifiers import allocate_identifier
from geni_studio.config.registry import template_file_error
from geni_studio.config.workflow_defs import (
    copy_workflow,
    create_workflow,
    delete_workflow,
    get_workflow,
    get_workflow_version,
    import_workflow,
    list_role_lanes,
    list_workflow_versions,
    list_workflows,
    save_as_subgraph,
    save_workflow,
    workflow_activity_roles,
    workflow_usage,
)
from geni_studio.config.workflow_templates import owned_name, owned_path, read_owned
from geni_studio.web.errors import http_error

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


class CreateWorkflowBody(BaseModel):
    workflow_id: str = ""
    title: str = ""


class SaveWorkflowBody(BaseModel):
    workflow_id: str = ""
    title: str = ""
    description: str = ""
    subgraph: bool = False
    workspace: str = ""
    rail: str = ""
    profile: dict[str, Any] | None = None
    nodes: list[dict[str, Any]] = Field(default_factory=list)


class ImportWorkflowBody(BaseModel):
    yaml: str = ""


class CopyWorkflowBody(BaseModel):
    title: str = ""


class SaveSubgraphBody(BaseModel):
    title: str = ""
    description: str = ""
    nodes: list[dict[str, Any]] = Field(default_factory=list)


def _http(exc: ConfigError) -> HTTPException:
    return http_error(exc)


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
        return save_as_subgraph(body.title, body.nodes, body.description, source_id=workflow_id)
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
        re.sub(r"-copy(-\d+)?$", "", workflow_id) + "-copy",
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


@router.post("/{workflow_id}/check")
def api_check_workflow(workflow_id: str, body: SaveWorkflowBody) -> dict:
    from geni_studio.workflows.executable import check_workflow

    try:
        get_workflow(workflow_id)
    except ConfigError as exc:
        raise _http(exc) from exc
    problems = check_workflow(body.model_dump(), workflow_id)
    return {"ok": not problems, "problems": problems}


def _workflow_folder(workflow_id: str) -> Path:
    try:
        get_workflow(workflow_id)
    except ConfigError as exc:
        raise _http(exc) from exc
    return factory_root() / "workflows" / workflow_id


@router.get("/{workflow_id}/templates/check")
def api_check_workflow_template(workflow_id: str, path: str = Query("")) -> dict:
    folder = _workflow_folder(workflow_id)
    text = path.strip()
    if owned_name(text):
        located = owned_path(folder, text)
        message = template_file_error(str(located)) if located else "模板路径不合规。"
    else:
        message = template_file_error(text)
    if message:
        raise HTTPException(status_code=400, detail=message)
    return {"path": text, "ok": True}


@router.get("/{workflow_id}/templates/content")
def api_workflow_template_content(workflow_id: str, path: str = Query("")) -> dict:
    folder = _workflow_folder(workflow_id)
    try:
        return {"path": path.strip(), "content": read_owned(folder, path.strip())}
    except ConfigError as exc:
        raise _http(exc) from exc


@router.get("/{workflow_id}/usage")
def api_workflow_usage(workflow_id: str) -> dict:
    try:
        get_workflow(workflow_id)
    except ConfigError as exc:
        raise _http(exc) from exc
    return workflow_usage(workflow_id)


@router.get("/{workflow_id}/versions")
def api_workflow_versions(workflow_id: str) -> dict:
    try:
        return {"versions": list_workflow_versions(workflow_id)}
    except ConfigError as exc:
        raise _http(exc) from exc


@router.get("/{workflow_id}/versions/{version}")
def api_workflow_version(workflow_id: str, version: int) -> dict:
    try:
        return get_workflow_version(workflow_id, version)
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


@router.delete("/{workflow_id}")
def api_delete_workflow(workflow_id: str) -> dict:
    try:
        delete_workflow(workflow_id)
    except ConfigError as exc:
        raise _http(exc) from exc
    return {"workflow_id": workflow_id, "deleted": True}
