"""FastAPI：Run 观测与 Web HITL（ADR 0003）。"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from geni_studio.config.context import ConfigError, build_run_context
from geni_studio.config.env_loader import bootstrap_env
from geni_studio.workspace.layout import WorkspaceError

bootstrap_env()
from geni_studio.hitl.feishu_notify import notify_awaiting_human_via_lark_cli
from geni_studio.hitl.rail import build_rail
from geni_studio.hitl.service import GraphRunService, HitlError, StopPending
from geni_studio.web.config_routes import router as config_router
from geni_studio.web.feishu_routes import bind_run_service
from geni_studio.web.feishu_routes import router as feishu_router
from geni_studio.web.role_routes import router as role_router
from geni_studio.web.workflow_routes import router as workflow_router
from geni_studio.workflows.default import graph


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    from geni_studio.hitl.feishu_bridge import start_background

    start_background()
    yield


app = FastAPI(title="GeniStudio", version="0.1.0", lifespan=_lifespan)
app.include_router(config_router)
app.include_router(workflow_router)
app.include_router(role_router)
app.include_router(feishu_router)
_static_dir = Path(__file__).with_name("static")
app.mount("/static", StaticFiles(directory=_static_dir), name="static")
_run_service = GraphRunService(graph)
bind_run_service(_run_service)


def _with_feishu(payload: dict, thread_id: str, project_id: str) -> dict:
    result = notify_awaiting_human_via_lark_cli(_run_service, thread_id, project_id)
    if result.sent or result.detail:
        payload = dict(payload)
        payload["feishu_notice"] = {"sent": result.sent, "detail": result.detail}
    return payload


class NodeToolChoice(BaseModel):
    skills: list[str] = Field(default_factory=list)
    mcp: list[str] = Field(default_factory=list)


class AttachmentRef(BaseModel):
    id: str
    name: str = ""
    size: int = 0


class StartRunBody(BaseModel):
    human_request: str = Field(min_length=1)
    scenario_key: str = ""
    project_id: str = ""
    thread_id: str | None = None
    run_name: str = ""
    node_tools: dict[str, NodeToolChoice] = Field(default_factory=dict)
    attachments: list[AttachmentRef] = Field(default_factory=list)
    role_models: dict[str, str] = Field(default_factory=dict)


class DeleteRunBody(BaseModel):
    confirm_name: str = ""


class HitlSubmitBody(BaseModel):
    gate_decision: Literal["approved", "rejected"] | None = None
    human_reply: str = ""
    channel: str = "web"
    escalation_choice: Literal["continue", "pause", "abort"] | None = None


def _static_html(name: str) -> str:
    return (Path(__file__).with_name("static") / name).read_text(encoding="utf-8")


@app.get("/", response_class=HTMLResponse)
@app.get("/project", response_class=HTMLResponse)
@app.get("/workflow", response_class=HTMLResponse)
@app.get("/role", response_class=HTMLResponse)
@app.get("/config", response_class=HTMLResponse)
@app.get("/help", response_class=HTMLResponse)
def console_ui() -> str:
    """人工处理、项目、流程与运行配置在同一文档里切换，避免一级菜单整页刷新。"""
    return _static_html("hitl.html")


@app.get("/api/rail")
def api_rail(scenario_key: str = "", project_id: str = "") -> dict:
    """启动前的轨道。已知场景时不列出未启用的节点。选定流程时只列出该流程的节点。"""
    skip: set[str] | None = None
    catalog = None
    meta = None
    if scenario_key.strip() or project_id.strip():
        try:
            ctx = build_run_context(
                scenario_key=scenario_key.strip(),
                project_id=project_id.strip(),
            )
            from geni_studio.config.workflow_defs import get_workflow, workflow_exists

            if ctx.profile_id.strip() and workflow_exists(ctx.profile_id.strip()):
                loaded = get_workflow(ctx.profile_id.strip())
                catalog, meta = _preview_catalog(loaded["workflow"])
                skip = set()
            else:
                from geni_studio.config.workflow_nodes import nodes_hidden_from_rail

                skip = nodes_hidden_from_rail(
                    skip_nodes=ctx.skip_nodes,
                    finance_enabled=ctx.feature_finance(),
                )
        except ConfigError:
            skip = None
            catalog = None
            meta = None
    else:
        from geni_studio.config.workflow_nodes import nodes_hidden_from_rail

        skip = nodes_hidden_from_rail(skip_nodes=set(), finance_enabled=False)
    return build_rail(
        phase="idle",
        next_nodes=[],
        awaiting=None,
        skip_nodes=skip,
        catalog=catalog,
        meta=meta,
    )


def _preview_catalog(workflow: dict) -> tuple[tuple[tuple[str, str], ...], dict]:
    items: list[tuple[str, str]] = []
    meta: dict = {}
    for node in workflow.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        node_id = str(node.get("id") or "")
        if not node_id:
            continue
        items.append((node_id, str(node.get("name") or node_id)))
        meta[node_id] = {
            "role": node.get("role") or "",
            "kind": node.get("kind") or "",
            "artifacts": list(node.get("outputs") or []),
        }
    return tuple(items), meta


class SaveRunDraftBody(BaseModel):
    draft_id: str = ""
    project_id: str = ""
    run_name: str = ""
    human_request: str = ""
    node_tools: dict[str, NodeToolChoice] = Field(default_factory=dict)
    attachments: list[AttachmentRef] = Field(default_factory=list)
    role_models: dict[str, str] = Field(default_factory=dict)


@app.get("/api/runs")
def api_list_runs(project_id: str = "", phase: str = "") -> dict:
    from geni_studio.hitl.drafts import list_drafts

    want = phase.strip()
    runs = [] if want == "saved" else _run_service.list_runs(project_id=project_id, phase=phase)
    if not want or want == "saved":
        runs = list_drafts(project_id=project_id) + runs
    return {"runs": runs}


@app.put("/api/runs/drafts")
def api_save_run_draft(body: SaveRunDraftBody) -> dict:
    from geni_studio.hitl.drafts import save_draft
    from geni_studio.hitl.run_name import taken_names_for_project
    from geni_studio.hitl.service import latest_run_records

    try:
        tools = _clean_node_tools(body.node_tools)
        taken = taken_names_for_project(latest_run_records(graph), body.project_id.strip())
        from geni_studio.hitl.attachments import clean_attachment_ids

        saved = save_draft(
            draft_id=body.draft_id,
            project_id=body.project_id,
            run_name=body.run_name,
            human_request=body.human_request,
            node_tools=tools,
            taken_names=taken,
            attachments=clean_attachment_ids(body.attachments),
            role_models=_clean_role_models(body.role_models),
        )
    except HitlError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return saved


@app.get("/api/runs/drafts/{draft_id}")
def api_get_run_draft(draft_id: str) -> dict:
    from geni_studio.hitl.drafts import load_draft

    try:
        return load_draft(draft_id)
    except HitlError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.post("/api/runs/{thread_id}/copy")
def api_copy_run(thread_id: str) -> dict:
    try:
        return _run_service.copy_run_template(thread_id.strip())
    except HitlError as e:
        missing = "未知" in str(e) or "无法识别" in str(e)
        raise HTTPException(status_code=404 if missing else 400, detail=str(e)) from e


@app.post("/api/runs/drafts/{draft_id}/delete")
def api_delete_run_draft(draft_id: str, body: DeleteRunBody) -> dict:
    from geni_studio.hitl.drafts import delete_draft

    try:
        delete_draft(draft_id, confirm_name=body.confirm_name)
    except HitlError as e:
        missing = "未知" in str(e) or "无法识别" in str(e)
        code = 409 if "不一致" in str(e) else (404 if missing else 400)
        raise HTTPException(status_code=code, detail=str(e)) from e
    return {"deleted": True, "draft_id": draft_id}


@app.post("/api/runs/attachments")
async def api_upload_attachment(request: Request) -> dict:
    from urllib.parse import unquote

    from geni_studio.hitl.attachments import store_upload

    filename = unquote(request.headers.get("x-filename") or "")
    data = await request.body()
    try:
        return store_upload(filename, data)
    except HitlError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/api/runs/next-name")
def api_next_run_name(project_id: str = "") -> dict:
    """新建 Run 时的默认名称：项目标识加递增序号。"""
    from geni_studio.hitl.run_name import next_run_name, taken_names_for_project
    from geni_studio.hitl.service import latest_run_records

    pid = project_id.strip()
    if not pid:
        raise HTTPException(status_code=400, detail="请先选择项目。")
    taken = taken_names_for_project(latest_run_records(graph), pid)
    return {"project_id": pid, "run_name": next_run_name(pid, taken)}


def _clean_role_models(raw: dict[str, str]) -> dict[str, str]:
    cleaned: dict[str, str] = {}
    for role, model in raw.items():
        key = str(role).strip()
        value = str(model or "").strip()
        if not key:
            raise ValueError("角色标识不能空。")
        if len(key) > 80 or len(value) > 120:
            raise ValueError("角色或模型标识过长。")
        if value:
            cleaned[key] = value
    return cleaned


def _clean_node_tools(raw: dict[str, NodeToolChoice]) -> dict[str, dict[str, list[str]]]:
    from geni_studio.backends.tools import clean_tool_ids

    cleaned: dict[str, dict[str, list[str]]] = {}
    for node_id, choice in raw.items():
        key = node_id.strip()
        if not key:
            raise ValueError("节点标识不能空。")
        skills = clean_tool_ids(choice.skills, "Skill")
        mcp = clean_tool_ids(choice.mcp, "MCP")
        if skills or mcp:
            cleaned[key] = {"skills": skills, "mcp": mcp}
    return cleaned


@app.post("/api/runs")
def api_start_run(body: StartRunBody) -> dict:
    import os

    from geni_studio.hitl.attachments import clean_attachment_ids

    try:
        tools = _clean_node_tools(body.node_tools)
        attachment_ids = clean_attachment_ids(body.attachments)
        kwargs = {
            "human_request": body.human_request,
            "scenario_key": body.scenario_key,
            "project_id": body.project_id,
            "thread_id": body.thread_id,
            "run_name": body.run_name,
            "node_tools": tools,
            "attachment_ids": attachment_ids,
            "role_models": _clean_role_models(body.role_models),
        }
        sync = os.environ.get("GENI_STUDIO_SYNC_START", "").strip().lower() in ("1", "true", "yes")
        if sync:
            st = _run_service.start(**kwargs)
            tid = st.thread_id
        else:
            tid, initial = _run_service.enqueue_start(**kwargs)
            try:
                payload = _run_service.status_dict(tid)
            except HitlError:
                payload = _run_service.provisional_status_dict(tid, initial)
            return _with_feishu(payload, tid, body.project_id)
    except (ConfigError, HitlError, WorkspaceError, ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return _with_feishu(_run_service.status_dict(tid), tid, body.project_id)


class RoleModelsBody(BaseModel):
    role_models: dict[str, str] = Field(default_factory=dict)


@app.put("/api/runs/{thread_id}/role-models")
def api_set_role_models(thread_id: str, body: RoleModelsBody) -> dict:
    try:
        st = _run_service.set_role_models(thread_id, _clean_role_models(body.role_models))
    except (HitlError, ValueError, TypeError) as e:
        missing = "未知" in str(e)
        raise HTTPException(status_code=404 if missing else 400, detail=str(e)) from e
    return _run_service.status_dict(st.thread_id)


@app.put("/api/runs/{thread_id}/nodes/{node_id}/tools")
def api_set_node_tools(thread_id: str, node_id: str, body: NodeToolChoice) -> dict:
    from geni_studio.backends.tools import clean_tool_ids

    try:
        skills = clean_tool_ids(body.skills, "Skill")
        mcp = clean_tool_ids(body.mcp, "MCP")
        st = _run_service.set_node_tools(thread_id, node_id, skills=skills, mcp=mcp)
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except HitlError as e:
        missing = "未知" in str(e)
        raise HTTPException(status_code=404 if missing else 400, detail=str(e)) from e
    return _run_service.status_dict(st.thread_id)


@app.post("/api/runs/{thread_id}/delete")
def api_delete_run(thread_id: str, body: DeleteRunBody) -> dict:
    try:
        _run_service.delete_run(thread_id, confirm_name=body.confirm_name)
    except HitlError as e:
        missing = "未知" in str(e)
        raise HTTPException(status_code=404 if missing else 409, detail=str(e)) from e
    return {"deleted": True, "thread_id": thread_id}


@app.get("/api/runs/{thread_id}/events")
def api_run_events(thread_id: str, once: int = 0):
    """运行中或等待人工时推送状态。其他阶段推送当前一帧后结束。"""
    import json
    import time

    def generate():
        previous = ""
        previous_conversation = ""
        while True:
            try:
                data = _run_service.status_dict(thread_id)
            except HitlError:
                yield "event: end\ndata: {}\n\n"
                return
            payload = json.dumps(data, ensure_ascii=False, default=str)
            if payload != previous:
                yield f"event: status\ndata: {payload}\n\n"
                previous = payload
            conv = _conversation_event(thread_id, data)
            if conv and conv != previous_conversation:
                yield f"event: conversation\ndata: {conv}\n\n"
                previous_conversation = conv
            if once or data.get("phase") not in ("running", "awaiting_human"):
                yield "event: end\ndata: {}\n\n"
                return
            time.sleep(0.25)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/runs/{thread_id}/artifacts/{key}")
def api_run_artifact(thread_id: str, key: str) -> dict:
    from geni_studio.hitl.conversation import read_artifact_text
    from geni_studio.workspace.persist import ARTIFACT_KEYS

    if key not in ARTIFACT_KEYS:
        raise HTTPException(status_code=404, detail="没有这份产物。")
    try:
        st = _run_service.status(thread_id)
    except HitlError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    workspace = str(st.values.get("workspace_path") or "")
    text = read_artifact_text(thread_id, key, workspace_path=workspace)
    if not text:
        raw = st.values.get(key)
        text = raw if isinstance(raw, str) else ""
    return {"key": key, "text": text}


@app.get("/api/runs/{thread_id}/conversations/{node_id}")
def api_run_conversation(thread_id: str, node_id: str) -> dict:
    try:
        data = _run_service.status_dict(thread_id)
    except HitlError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    from geni_studio.hitl.conversation import conversation_view
    from geni_studio.hitl.rail import NODE_ROLE

    role = NODE_ROLE.get(node_id, "")
    workspace = str((data.get("values") or {}).get("workspace_path") or "")
    view = conversation_view(thread_id, role, workspace_path=workspace) if role else {"role": "", "turns": []}
    view["node"] = node_id
    return view


def _conversation_event(thread_id: str, data: dict) -> str:
    import json

    from geni_studio.hitl.conversation import conversation_view
    from geni_studio.hitl.rail import NODE_ROLE

    node = str((data.get("rail") or {}).get("current") or "")
    role = NODE_ROLE.get(node, "")
    if not role:
        return ""
    workspace = str((data.get("values") or {}).get("workspace_path") or "")
    view = conversation_view(thread_id, role, workspace_path=workspace)
    if not view["turns"]:
        return ""
    view["node"] = node
    return json.dumps(view, ensure_ascii=False, default=str)


@app.get("/api/runs/{thread_id}")
def api_run_status(thread_id: str) -> dict:
    fail = _run_service.start_failure_message(thread_id)
    if fail:
        raise HTTPException(status_code=400, detail=fail)
    try:
        return _run_service.status_dict(thread_id)
    except HitlError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.post("/api/runs/{thread_id}/pause")
def api_pause_run(thread_id: str) -> dict:
    try:
        st = _run_service.pause(thread_id)
    except HitlError as e:
        code = 404 if "未知" in str(e) else 409
        raise HTTPException(status_code=code, detail=str(e)) from e
    return _run_service.status_dict(st.thread_id)


@app.post("/api/runs/{thread_id}/continue")
def api_continue_run(thread_id: str) -> dict:
    try:
        st = _run_service.continue_interrupted(thread_id)
    except HitlError as e:
        code = 404 if "未知" in str(e) else 409
        raise HTTPException(status_code=code, detail=str(e)) from e
    return _with_feishu(
        _run_service.status_dict(st.thread_id),
        st.thread_id,
        str(st.values.get("project_id") or ""),
    )


@app.post("/api/runs/{thread_id}/resume")
def api_resume_run(thread_id: str) -> dict:
    try:
        st = _run_service.resume(thread_id)
    except HitlError as e:
        code = 404 if "未知" in str(e) else 409
        raise HTTPException(status_code=code, detail=str(e)) from e
    return _with_feishu(
        _run_service.status_dict(st.thread_id),
        st.thread_id,
        str(st.values.get("project_id") or ""),
    )


@app.post("/api/runs/{thread_id}/stop")
def api_stop_run(thread_id: str) -> dict:
    try:
        st = _run_service.stop(thread_id)
    except StopPending:
        return {
            "thread_id": thread_id,
            "phase": "running",
            "stop_requested": True,
            "next_nodes": [],
            "awaiting_human": None,
            "values": {},
            "rail": build_rail(
                phase="running",
                next_nodes=[],
                awaiting=None,
                skip_nodes=None,
            ),
            "reading": [],
        }
    except HitlError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    return _run_service.status_dict(st.thread_id)


@app.post("/api/runs/{thread_id}/hitl")
def api_submit_hitl(thread_id: str, body: HitlSubmitBody) -> dict:
    try:
        st = _run_service.submit_hitl(
            thread_id,
            gate_decision=body.gate_decision,
            human_reply=body.human_reply,
            channel=body.channel,
            escalation_choice=body.escalation_choice,
        )
    except HitlError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
    project_id = str(st.values.get("project_id") or "")
    return _with_feishu(_run_service.status_dict(thread_id), thread_id, project_id)


def main() -> None:
    import os

    import uvicorn

    os.environ.setdefault("GENI_STUDIO_FEISHU_BRIDGE", "1")
    uvicorn.run(
        "geni_studio.web.app:app",
        host="127.0.0.1",
        port=8765,
        reload=False,
    )


if __name__ == "__main__":
    main()
