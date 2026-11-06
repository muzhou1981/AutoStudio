"""已实现功能的补充用例：快照、列表、超时、检视数据、命令边界、复盘和暂停续跑。"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from auto_studio.hitl.feishu_cards import build_gate_interactive_card
from auto_studio.hitl.feishu_status import status_lines_for_thread
from auto_studio.hitl.rail import build_rail
from auto_studio.hitl.service import GraphRunService
from auto_studio.verification.command import assert_command_cwd
from auto_studio.verification.retro import scorecard
from auto_studio.web.app import app
from auto_studio.workflows.default import compile_graph, graph


@pytest.fixture
def svc() -> GraphRunService:
    return GraphRunService(graph)


def test_project_snapshot_stays_after_the_file_would_change(
    svc: GraphRunService, monkeypatch: pytest.MonkeyPatch
) -> None:
    st = svc.start(human_request="项目快照", project_id="_example", run_name="快照轮")
    frozen = str(st.values.get("config_snapshot_project") or "")
    assert "title: 示例项目" in frozen
    assert "scenario_key: npu_operator" in str(st.values.get("config_snapshot_scenario") or "")
    monkeypatch.setattr(
        "auto_studio.config.registry.get_project_yaml",
        lambda *args, **kwargs: "project_id: _example\ntitle: 后来改过\n",
    )
    again = svc.status(st.thread_id)
    assert again.values.get("config_snapshot_project") == frozen
    assert "后来改过" not in str(again.values.get("config_snapshot_project"))


def test_run_list_filters_by_project_and_reports_retry_limit(svc: GraphRunService) -> None:
    st = svc.start(human_request="列表项目", project_id="_example", run_name="项目列表")
    matched = svc.list_runs(project_id="_example")
    assert any(row["thread_id"] == st.thread_id and row["run_name"] == "项目列表" for row in matched)
    assert all(row["project_id"] == "_example" for row in matched)
    other = svc.list_runs(project_id="helloworld")
    assert all(row["thread_id"] != st.thread_id for row in other)
    data = svc.status_dict(st.thread_id)
    assert data["limits"]["max_dev_retries"] == 5
    assert data["rail"]["current"] == "gate_requirement_confirm"


def test_gate_timeout_waits_then_records_and_approval_still_advances(
    svc: GraphRunService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AUTO_STUDIO_GATE_TIMEOUT_SECONDS", "86400")
    st = svc.start(human_request="时限内", scenario_key="npu_operator")
    early = svc.status_dict(st.thread_id)
    assert early["phase"] == "awaiting_human"
    assert not early["values"].get("gate_timeout_recorded")
    assert early["values"].get("awaiting_since")

    monkeypatch.setenv("AUTO_STUDIO_GATE_TIMEOUT_SECONDS", "0")
    late = svc.status_dict(st.thread_id)
    assert late["phase"] == "awaiting_human"
    assert late["next_nodes"] == ["gate_requirement_confirm"]
    lines = status_lines_for_thread(svc, st.thread_id, "http://127.0.0.1:8767/")
    assert lines[2] == "待办：待批复 · 需求确认（超时未批复）"
    card = build_gate_interactive_card(
        thread_id=st.thread_id,
        summary=late["awaiting_human"]["summary"],
        gate_id="gate_requirement_confirm",
        web_url="http://127.0.0.1:8767/",
    )
    dumped = str(card)
    assert "批准" in dumped
    assert "gate_decision" in dumped

    advanced = svc.submit_hitl(st.thread_id, gate_decision="approved", human_reply="超时后仍可批")
    assert advanced.phase == "awaiting_human"
    assert advanced.awaiting_human is not None
    assert advanced.awaiting_human.gate_id == "gate_architecture_review"
    assert not advanced.values.get("gate_timeout_note")


def test_console_markup_has_list_inspect_and_resize_handles() -> None:
    text = TestClient(app).get("/").text
    assert 'id="runPhaseFilter"' in text
    assert ">Run列表</span>" in text
    assert 'value="all"' in text
    assert "runListSeq" in text
    assert 'id="runList"' in text
    assert 'name.className = "run-name"' in text
    assert "PHASE_ICON" in text
    assert "run-phase-svg" in text
    assert "is-spin" in text
    assert 'key === "awaiting_human"' in text
    assert "fill-rule" in text
    assert "run-delete-icon" in text
    assert 'del.textContent = "删除"' not in text
    assert 'id="sidebarResize"' in text
    assert 'class="inspect-resize"' in text
    assert "调用次数" in text
    assert "开发重试" in text
    assert ">启动</wa-button>" in text
    assert ">暂停</wa-button>" in text
    assert ">停止</wa-button>" in text
    assert "启动本轮" not in text
    assert "暂停本轮" not in text
    assert "停止本轮" not in text


def test_command_cwd_allows_a_subdirectory_and_rejects_a_sibling(tmp_path) -> None:
    from auto_studio.verification.command import TestCommandError

    workspace = tmp_path / "tree"
    nested = workspace / "pkg"
    nested.mkdir(parents=True)
    sibling = tmp_path / "other"
    sibling.mkdir()
    assert_command_cwd(nested, workspace)
    with pytest.raises(TestCommandError, match="工作目录"):
        assert_command_cwd(sibling, workspace)


def test_scorecard_emits_three_items_each_and_stays_pending() -> None:
    text = scorecard(
        {
            "dev_retry_count": 0,
            "qa_status": "pass",
            "baseline_log": "[baseline:gate_requirement_confirm] decision=approved at=t",
            "requirement_spec": "AC-1 必须出现",
            "test_report": "AC-1 passed",
            "cost_ledger": "role=tester backend=stub cost=0",
        }
    )
    assert len(re.findall(r"(?m)^\d+\. ", text)) == 6
    assert "验收编号均出现在测试或 QA 证据中。" in text
    assert "dev_retry_count=0" in text
    assert "提案状态：pending" in text
    assert "未经批准不得修改角色定义或流程" in text


def test_rail_markers_are_not_skipped() -> None:
    rail = build_rail(
        phase="running",
        next_nodes=["developer"],
        awaiting=None,
        skip_nodes={"run_start", "run_end", "ux_designer"},
    )
    states = {cell["id"]: cell["state"] for cell in rail["cells"]}
    assert states["run_start"] == "done"
    assert states["run_end"] == "pending"
    assert "ux_designer" not in states
    assert states["developer"] == "active"


def test_paused_round_resumes_on_a_new_graph(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from auto_studio.backends.runner import invoke_role
    from auto_studio.hitl.control import RunPaused, current_thread_id, request_pause
    from auto_studio.workspace.checkpoint import sqlite_checkpointer

    once = {"done": False}

    def wrapped(**kwargs):
        if not once["done"]:
            once["done"] = True
            request_pause(current_thread_id())
            raise RunPaused("本轮已暂停")
        return invoke_role(**kwargs)

    monkeypatch.setattr("auto_studio.backends.runner.invoke_role", wrapped)
    path = tmp_path / "paused.sqlite"
    first = GraphRunService(compile_graph(sqlite_checkpointer(path)))
    paused = first.start(human_request="暂停续", scenario_key="npu_operator", run_name="暂停样本")
    assert paused.phase == "paused"
    second = GraphRunService(compile_graph(sqlite_checkpointer(path)))
    reopened = second.status(paused.thread_id)
    assert reopened.phase == "paused"
    assert reopened.values.get("run_name") == "暂停样本"
    resumed = second.resume(paused.thread_id)
    assert resumed.phase == "awaiting_human"
    assert resumed.awaiting_human is not None
    assert resumed.awaiting_human.gate_id == "gate_requirement_confirm"
    assert resumed.values.get("requirement_spec")
