"""不依赖 Cursor 桥的运行列表、配置快照、关卡超时、复盘证据和断线续跑。"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from auto_studio.hitl.service import GraphRunService
from auto_studio.verification.retro import scorecard
from auto_studio.web.app import app
from auto_studio.workflows.default import graph


@pytest.fixture
def svc() -> GraphRunService:
    return GraphRunService(graph)


def test_start_freezes_the_scenario_snapshot(svc: GraphRunService) -> None:
    st = svc.start(human_request="快照", scenario_key="npu_operator")
    text = str(st.values.get("config_snapshot_scenario") or "")
    assert "scenario_key: npu_operator" in text
    assert st.values.get("scenario_key") == "npu_operator"
    assert st.values.get("config_snapshot_project") == ""


def test_run_list_filters_by_phase(svc: GraphRunService) -> None:
    st = svc.start(human_request="列表", scenario_key="npu_operator", run_name="列表样本")
    rows = svc.list_runs(phase="awaiting_human")
    found = [row for row in rows if row["thread_id"] == st.thread_id]
    assert found
    assert found[0]["run_name"] == "列表样本"
    assert found[0]["phase"] == "awaiting_human"
    assert svc.list_runs(phase="completed") == [] or all(
        row["thread_id"] != st.thread_id for row in svc.list_runs(phase="completed")
    )
    client = TestClient(app)
    listed = client.get("/api/runs", params={"phase": "awaiting_human"})
    assert listed.status_code == 200
    assert any(row["thread_id"] == st.thread_id for row in listed.json()["runs"])


def test_gate_timeout_records_without_leaving_the_gate(svc: GraphRunService, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTO_STUDIO_GATE_TIMEOUT_SECONDS", "0")
    st = svc.start(human_request="超时", scenario_key="npu_operator")
    data = svc.status_dict(st.thread_id)
    assert data["phase"] == "awaiting_human"
    assert data["values"]["gate_timeout_recorded"] is True
    assert "超时未批复" in data["values"]["gate_timeout_note"]
    assert data["awaiting_human"]["gate_id"] == "gate_requirement_confirm"
    assert data["next_nodes"] == ["gate_requirement_confirm"]
    again = svc.status_dict(st.thread_id)
    assert again["values"]["hitl_audit_log"].count("[timeout]") == 1


def test_scorecard_uses_rework_acceptance_and_cost():
    text = scorecard(
        {
            "dev_retry_count": 2,
            "qa_status": "fail",
            "baseline_log": "[baseline:gate_requirement_confirm] decision=rejected at=t",
            "requirement_spec": "AC-1 必须通过\nAC-2 必须记录",
            "test_report": "AC-1 passed",
            "qa_report": "",
            "cost_ledger": "role=developer backend=stub cost=0",
        }
    )
    assert "dev_retry_count=2" in text
    assert "AC-2" in text
    assert "1 行调用记录" in text
    assert "驳回" in text
    assert "提案状态：pending" in text
    assert "## Top3 有价值" in text
    assert "## Top3 待改进" in text


def test_process_restart_reopens_and_continues(tmp_path) -> None:
    path = tmp_path / "checkpoints.sqlite"
    env = os.environ.copy()
    env["AUTO_STUDIO_CHECKPOINT"] = "sqlite"
    env["AUTO_STUDIO_CHECKPOINT_PATH"] = str(path)
    env["AUTO_STUDIO_BACKEND"] = "stub"
    env["AUTO_STUDIO_WORKSPACE"] = "0"
    code = """
import os, sys
os.environ["AUTO_STUDIO_CHECKPOINT"] = "sqlite"
os.environ["AUTO_STUDIO_CHECKPOINT_PATH"] = sys.argv[1]
os.environ["AUTO_STUDIO_BACKEND"] = "stub"
os.environ["AUTO_STUDIO_WORKSPACE"] = "0"
from auto_studio.hitl.service import GraphRunService
from auto_studio.workflows.default import compile_graph
from pathlib import Path

from auto_studio.workspace.checkpoint import sqlite_checkpointer

svc = GraphRunService(compile_graph(sqlite_checkpointer(Path(sys.argv[1]))))
action = sys.argv[2]
if action == "start":
    st = svc.start(human_request="断线", scenario_key="npu_operator", run_name="续跑样本")
    print(st.thread_id)
    print(st.phase)
elif action == "status":
    st = svc.status(sys.argv[3])
    print(st.phase)
    print(st.awaiting_human.gate_id if st.awaiting_human else "")
    print(st.values.get("run_name") or "")
elif action == "approve":
    st = svc.submit_hitl(sys.argv[3], gate_decision="approved", human_reply="继续")
    print(st.phase)
    print(st.awaiting_human.gate_id if st.awaiting_human else "")
"""
    start = subprocess.run(
        [sys.executable, "-c", code, str(path), "start"],
        cwd=os.fspath(tmp_path),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert start.returncode == 0, start.stderr
    thread_id, phase = start.stdout.strip().splitlines()[-2:]
    assert phase == "awaiting_human"
    status = subprocess.run(
        [sys.executable, "-c", code, str(path), "status", thread_id],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert status.returncode == 0, status.stderr
    lines = status.stdout.strip().splitlines()
    assert lines[-3:] == ["awaiting_human", "gate_requirement_confirm", "续跑样本"]
    approved = subprocess.run(
        [sys.executable, "-c", code, str(path), "approve", thread_id],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert approved.returncode == 0, approved.stderr
    assert approved.stdout.strip().splitlines()[-2] == "awaiting_human"
    assert approved.stdout.strip().splitlines()[-1] == "gate_architecture_review"
