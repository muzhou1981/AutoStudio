"""角色的增加、修改和删除。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from geni_studio.config.context import ConfigError
from geni_studio.roles.admin import (
    create_role,
    delete_role,
    get_role,
    list_artifact_choices,
    list_roles,
    save_role,
)

router = APIRouter(prefix="/api/roles", tags=["roles"])


class CreateRoleBody(BaseModel):
    title: str = ""


class SaveRoleBody(BaseModel):
    title: str = ""
    category: str = "execution"
    responsibilities: list[str] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    body: str = ""


def _http(exc: ConfigError) -> HTTPException:
    missing = str(exc).startswith("角色不存在")
    return HTTPException(status_code=404 if missing else 400, detail=str(exc))


@router.get("")
def api_list_roles() -> dict[str, Any]:
    return {"roles": list_roles(), "artifacts": list_artifact_choices()}


@router.post("")
def api_create_role(body: CreateRoleBody) -> dict[str, Any]:
    try:
        return {"role": create_role(body.title)}
    except ConfigError as exc:
        raise _http(exc) from exc


@router.get("/{role_id}")
def api_get_role(role_id: str) -> dict[str, Any]:
    try:
        return {"role": get_role(role_id)}
    except ConfigError as exc:
        raise _http(exc) from exc


@router.put("/{role_id}")
def api_save_role(role_id: str, body: SaveRoleBody) -> dict[str, Any]:
    try:
        return {"role": save_role(role_id, body.model_dump())}
    except ConfigError as exc:
        raise _http(exc) from exc


@router.delete("/{role_id}")
def api_delete_role(role_id: str) -> dict[str, Any]:
    try:
        delete_role(role_id)
    except ConfigError as exc:
        raise _http(exc) from exc
    return {"ok": True}
