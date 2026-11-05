"""FastAPI：Run 观测与 Web HITL（ADR 0003）。"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from auto_studio.config.context import ConfigError
from auto_studio.hitl.feishu_notify import notify_awaiting_human_via_lark_cli
from auto_studio.hitl.service import GraphRunService, HitlError
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


class HitlSubmitBody(BaseModel):
    gate_decision: Literal["approved", "rejected"] | None = None
    human_reply: str = ""
    channel: str = "web"
    escalation_choice: Literal["continue", "pause", "abort"] | None = None


def _static_html(name: str) -> str:
    return (Path(__file__).with_name("static") / name).read_text(encoding="utf-8")


@app.get("/", response_class=HTMLResponse)
def hitl_ui() -> str:
    return _static_html("hitl.html")


@app.get("/config", response_class=HTMLResponse)
def config_ui() -> str:
    return _static_html("config.html")


@app.post("/api/runs")
def api_start_run(body: StartRunBody) -> dict:
    try:
        st = _run_service.start(
            human_request=body.human_request,
            scenario_key=body.scenario_key,
            project_id=body.project_id,
            thread_id=body.thread_id,
        )
    except ConfigError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    notify_awaiting_human_via_lark_cli(_run_service, st.thread_id, body.project_id)
    return _run_service.status_dict(st.thread_id)


@app.get("/api/runs/{thread_id}")
def api_run_status(thread_id: str) -> dict:
    try:
        return _run_service.status_dict(thread_id)
    except HitlError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


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
