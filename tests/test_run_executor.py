"""运行执行器与任务表：请求不阻塞、跨进程停止、崩溃恢复、只读状态、运行索引与有界缓存。"""

from __future__ import annotations

import socket

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

from geni_studio.hitl.service import GraphRunService, HitlError
from geni_studio.runtime.executor import Executor
from geni_studio.runtime.store import RuntimeStore, _connect
from geni_studio.workflows.default import compile_graph


@pytest.fixture
def svc() -> GraphRunService:
    return GraphRunService(compile_graph(checkpointer=MemorySaver()))


def _checkpoint_id(svc: GraphRunService, thread_id: str) -> str:
    snap = svc._bound(thread_id).get_state(svc._config(thread_id))
    return str(snap.config["configurable"].get("checkpoint_id") or "")


def test_hitl_request_returns_before_the_graph_moves(svc, monkeypatch):
    st = svc.start(human_request="入队", scenario_key="npu_operator")
    assert st.awaiting_human is not None and st.awaiting_human.gate_id == "gate_requirement_confirm"
    monkeypatch.setenv("GENI_STUDIO_EXECUTOR", "external")

    queued = svc.request_hitl(st.thread_id, gate_decision="approved")
    assert queued.phase == "running"
    job = svc.runtime_store().active_job(st.thread_id)
    assert job is not None and job.state == "queued" and job.kind == "invoke"
    with pytest.raises(HitlError, match="待执行"):
        svc.request_hitl(st.thread_id, gate_decision="approved")

    worker = Executor(svc, workers=1)
    assert worker.run_once() is not None
    moved = svc.status(st.thread_id)
    assert moved.phase == "awaiting_human"
    assert moved.awaiting_human is not None
    assert moved.awaiting_human.gate_id != "gate_requirement_confirm"
    assert svc.runtime_store().active_job(st.thread_id) is None


def test_web_start_and_hitl_only_enqueue_in_external_mode(monkeypatch):
    from geni_studio.web.app import run_service

    monkeypatch.setenv("GENI_STUDIO_EXECUTOR", "external")
    client = TestClient(app_module())
    started = client.post("/api/runs", json={"human_request": "外部执行", "scenario_key": "npu_operator"})
    assert started.status_code == 200
    tid = started.json()["thread_id"]
    assert started.json()["phase"] == "running"
    assert client.get(f"/api/runs/{tid}").json()["phase"] == "running"

    job = run_service().runtime_store().active_job(tid)
    assert job is not None and job.kind == "start"
    Executor(run_service(), workers=1).run_once(job_id=job.id)
    data = client.get(f"/api/runs/{tid}").json()
    assert data["phase"] == "awaiting_human"

    sent = client.post(f"/api/runs/{tid}/hitl", json={"gate_decision": "approved"})
    assert sent.status_code == 200
    assert sent.json()["phase"] == "running"
    assert sent.json()["job"]["state"] == "queued"
    job = run_service().runtime_store().active_job(tid)
    Executor(run_service(), workers=1).run_once(job_id=job.id)
    assert client.get(f"/api/runs/{tid}").json()["phase"] == "awaiting_human"


def app_module():
    from geni_studio.web.app import app

    return app


def test_stop_written_by_another_process_reaches_the_worker(svc, tmp_path):
    from geni_studio.hitl.control import clear_stop_request, is_stop_requested

    path = str(tmp_path / "runtime.sqlite")
    svc._store = RuntimeStore(_connect(path))
    web_side = RuntimeStore(_connect(path))
    worker = Executor(svc, workers=1)
    job = svc.runtime_store().enqueue("cross-process", "invoke")
    assert svc.runtime_store().claim(worker.worker, job_id=job.id) is not None
    try:
        web_side.set_control("cross-process", stop=True)
        worker.apply_controls()
        assert is_stop_requested("cross-process")
    finally:
        clear_stop_request("cross-process")


def test_job_of_a_dead_worker_is_failed_on_recovery(svc, monkeypatch):
    monkeypatch.setenv("GENI_STUDIO_EXECUTOR", "external")
    tid, _initial = svc.enqueue_start(human_request="崩溃", scenario_key="npu_operator")
    dead = f"{socket.gethostname()}:999999999:dead"
    assert svc.runtime_store().claim(dead) is not None
    assert svc.view(tid)["phase"] == "running"

    recovered = Executor(svc, workers=1).recover()
    assert [job.thread_id for job in recovered] == [tid]
    assert svc.runtime_store().active_job(tid) is None
    assert "执行进程已退出" in str(svc.start_failure_message(tid))


def test_status_reads_do_not_write_checkpoints(svc, monkeypatch):
    monkeypatch.setenv("GENI_STUDIO_GATE_TIMEOUT_SECONDS", "0")
    st = svc.start(human_request="只读", scenario_key="npu_operator")
    before = _checkpoint_id(svc, st.thread_id)
    data = svc.status_dict(st.thread_id)
    assert data["values"]["gate_timeout_recorded"] is True
    assert _checkpoint_id(svc, st.thread_id) == before

    svc._bound(st.thread_id).update_state(svc._config(st.thread_id), {}, as_node="project_manager_draft")
    before = _checkpoint_id(svc, st.thread_id)
    assert svc.status_dict(st.thread_id)["phase"] == "interrupted"
    assert _checkpoint_id(svc, st.thread_id) == before


def test_run_list_and_names_come_from_the_index(svc, monkeypatch):
    first = svc.start(human_request="索引一", scenario_key="npu_operator", run_name="idx-1")
    svc.start(human_request="索引二", scenario_key="npu_operator", run_name="idx-2")
    svc.list_runs()

    def no_scan(*_args, **_kwargs):
        raise AssertionError("列表不应再扫描检查点")

    monkeypatch.setattr("geni_studio.hitl.service.latest_run_records", no_scan)
    rows = svc.list_runs()
    assert {row["run_name"] for row in rows} == {"idx-1", "idx-2"}
    assert svc.taken_run_names("") == {"idx-1", "idx-2"}
    assert {row["phase"] for row in svc.list_runs(phase="awaiting_human")} == {"awaiting_human"}

    svc.delete_run(first.thread_id, confirm_name="idx-1")
    assert svc.taken_run_names("") == {"idx-2"}


def test_graph_cache_is_bounded(svc):
    from geni_studio.hitl import service as service_module

    for index in range(service_module._GRAPH_CACHE_SIZE + 10):
        svc._remember_graph(f"cache-{index}", svc._graph)
    assert len(svc._graphs) == service_module._GRAPH_CACHE_SIZE
    assert "cache-0" not in svc._graphs


def test_write_busy_defers_the_job(svc, monkeypatch):
    from geni_studio.workspace.policy import WriteBusy

    job = svc.runtime_store().enqueue("busy-thread", "invoke")

    def busy(_job):
        raise WriteBusy("工作区正被另一轮写入")

    monkeypatch.setattr(svc, "execute_job", busy)
    worker = Executor(svc, workers=1)
    assert worker.run_once(job_id=job.id) is not None
    again = svc.runtime_store().active_job("busy-thread")
    assert again is not None and again.state == "queued"
    assert "等待写锁" in again.note
    assert worker.run_once() is None


def test_feishu_card_callback_only_enqueues(monkeypatch):
    import time

    from geni_studio.web.app import run_service

    st = run_service().start(human_request="飞书回调", scenario_key="npu_operator")
    monkeypatch.setenv("GENI_STUDIO_EXECUTOR", "external")
    body = {
        "header": {"event_type": "card.action.trigger"},
        "event": {"action": {"value": {"thread_id": st.thread_id, "hitl_action": "gate", "gate_decision": "approved"}}},
    }
    began = time.monotonic()
    answered = TestClient(app_module()).post("/api/webhooks/feishu", json=body)
    elapsed = time.monotonic() - began
    assert answered.status_code == 200
    assert answered.json()["phase"] == "running"
    assert elapsed < 2.0
    job = run_service().runtime_store().active_job(st.thread_id)
    assert job is not None and job.state == "queued"
    Executor(run_service(), workers=1).run_once(job_id=job.id)
    assert run_service().status(st.thread_id).phase == "awaiting_human"
