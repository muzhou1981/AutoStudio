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

_UNFINISHED_PHASES = frozenset({"running", "awaiting_human", "paused", "interrupted"})


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


_OVERVIEW_RECENT = 5
_OVERVIEW_SCAN = 50


@router.get("/projects/{project_id}/overview")
def api_project_overview(project_id: str) -> dict:
    """项目右栏：选定的流程、实际工作区与落地方式、最近的 Run，以及代码尚未回到项目目录的 Run。"""
    from pathlib import Path

    from geni_studio.config.workflow_defs import list_workflows
    from geni_studio.web.app import run_service
    from geni_studio.workspace.pending import current_branch, run_leftover

    try:
        form = project_form_view(project_id)
    except ConfigError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    profile_id = str(form.get("profile_id") or "")
    flow = next((item for item in list_workflows() if item["workflow_id"] == profile_id), None)
    repo = Path(str(form.get("workspace_resolved") or ""))
    is_dir = bool(form.get("workspace_resolved")) and repo.is_dir()
    runs = run_service().list_runs(project_id=project_id)
    pending: list[dict] = []
    for run in runs[:_OVERVIEW_SCAN]:
        phase = str(run.get("phase") or "")
        reason = "未结束" if phase in _UNFINISHED_PHASES else (run_leftover(repo, run["thread_id"]) if is_dir else "")
        if reason:
            pending.append({**_run_brief(run), "reason": reason})
    return {
        "project_id": project_id,
        "flow": {
            "workflow_id": profile_id,
            "title": flow["title"] if flow else profile_id,
            "exists": flow is not None,
            "workspace": flow["workspace"] if flow else "",
        }
        if profile_id
        else None,
        "workspace": {
            "configured": str(form.get("workspace") or ""),
            "path": str(form.get("workspace_resolved") or ""),
            "exists": is_dir,
            "branch": current_branch(repo) if is_dir else "",
        },
        "runs": [_run_brief(run) for run in runs[:_OVERVIEW_RECENT]],
        "run_count": len(runs),
        "unfinished": sum(1 for run in runs if run.get("phase") in _UNFINISHED_PHASES),
        "pending": pending,
    }


def _run_brief(run: dict) -> dict:
    return {
        "thread_id": run["thread_id"],
        "run_name": run.get("run_name") or run["thread_id"],
        "phase": run.get("phase") or "",
        "updated_at": run.get("updated_at"),
    }


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
    from geni_studio.web.app import run_service

    open_runs = [
        str(run.get("run_name") or run.get("thread_id"))
        for run in run_service().list_runs(project_id=project_id)
        if run.get("phase") in _UNFINISHED_PHASES
    ]
    if open_runs:
        raise HTTPException(
            status_code=409,
            detail="这个项目还有未结束的 Run：" + "、".join(open_runs) + "。先停止或等它们结束，再删除项目。",
        )
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
        yaml_text = f"project_id: {project_id}\ntitle: {title or project_id}\n"
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
