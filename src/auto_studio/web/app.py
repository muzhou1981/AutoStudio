"""FastAPI：Run 观测与 Web HITL（ADR 0003）。"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from auto_studio.config.context import ConfigError, build_run_context
from auto_studio.config.env_loader import apply_env_file

apply_env_file()
from auto_studio.hitl.feishu_notify import notify_awaiting_human_via_lark_cli
from auto_studio.hitl.rail import build_rail
from auto_studio.hitl.service import GraphRunService, HitlError, StopPending
from auto_studio.web.config_routes import router as config_router
from auto_studio.web.feishu_routes import bind_run_service
from auto_studio.web.feishu_routes import router as feishu_router
from auto_studio.workflows.default import graph

app = FastAPI(title="auto_studio", version="0.1.0")
app.include_router(config_router)
app.include_router(feishu_router)
_static_dir = Path(__file__).with_name("static")
app.mount("/static", StaticFiles(directory=_static_dir), name="static")
_run_service = GraphRunService(graph)
bind_run_service(_run_service)


class StartRunBody(BaseModel):
    human_request: str = Field(min_length=1)
    scenario_key: str = ""
    project_id: str = ""
    thread_id: str | None = None
    run_name: str = ""


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
@app.get("/config", response_class=HTMLResponse)
def console_ui() -> str:
    """人工处理、项目配置与运行配置在同一文档里切换，避免一级菜单整页刷新。"""
    return _static_html("hitl.html")


@app.get("/api/rail")
def api_rail(scenario_key: str = "", project_id: str = "") -> dict:
    """启动前的轨道。已知场景时不列出未启用的节点。"""
    skip: set[str] | None = None
    if scenario_key.strip() or project_id.strip():
        try:
            ctx = build_run_context(
                scenario_key=scenario_key.strip(),
                project_id=project_id.strip(),
            )
            from auto_studio.config.workflow_nodes import nodes_hidden_from_rail

            skip = nodes_hidden_from_rail(
                skip_nodes=ctx.skip_nodes,
                finance_enabled=ctx.feature_finance(),
            )
        except ConfigError:
            skip = None
    return build_rail(phase="idle", next_nodes=[], awaiting=None, skip_nodes=skip)


@app.get("/api/runs")
def api_list_runs(project_id: str = "", phase: str = "") -> dict:
    return {"runs": _run_service.list_runs(project_id=project_id, phase=phase)}


@app.get("/api/runs/next-name")
def api_next_run_name(project_id: str = "") -> dict:
    """新建 Run 时的默认名称：项目标识加递增序号。"""
    from auto_studio.hitl.run_name import next_run_name, taken_names_for_project
    from auto_studio.hitl.service import latest_run_records

    pid = project_id.strip()
    if not pid:
        raise HTTPException(status_code=400, detail="请先选择项目。")
    taken = taken_names_for_project(latest_run_records(graph), pid)
    return {"project_id": pid, "run_name": next_run_name(pid, taken)}


@app.post("/api/runs")
def api_start_run(body: StartRunBody) -> dict:
    try:
        st = _run_service.start(
            human_request=body.human_request,
            scenario_key=body.scenario_key,
            project_id=body.project_id,
            thread_id=body.thread_id,
            run_name=body.run_name,
        )
    except (ConfigError, HitlError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    notify_awaiting_human_via_lark_cli(_run_service, st.thread_id, body.project_id)
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
            if once or data.get("phase") not in ("running", "awaiting_human"):
                yield "event: end\ndata: {}\n\n"
                return
            time.sleep(0.4)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/runs/{thread_id}")
def api_run_status(thread_id: str) -> dict:
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


@app.post("/api/runs/{thread_id}/resume")
def api_resume_run(thread_id: str) -> dict:
    try:
        st = _run_service.resume(thread_id)
    except HitlError as e:
        code = 404 if "未知" in str(e) else 409
        raise HTTPException(status_code=code, detail=str(e)) from e
    return _run_service.status_dict(st.thread_id)


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
    notify_awaiting_human_via_lark_cli(_run_service, thread_id, project_id)
    return _run_service.status_dict(thread_id)


def main() -> None:
    import uvicorn

    uvicorn.run(
        "auto_studio.web.app:app",
        host="127.0.0.1",
        port=8765,
        reload=False,
    )


if __name__ == "__main__":
    main()
