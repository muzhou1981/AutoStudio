"""已实现功能的补充用例：快照、列表、超时、检视数据、命令边界、复盘和暂停续跑。"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from geni_studio.hitl.feishu_cards import build_gate_interactive_card
from geni_studio.hitl.feishu_status import status_lines_for_thread
from geni_studio.hitl.rail import build_rail
from geni_studio.hitl.service import GraphRunService
from geni_studio.verification.command import assert_command_cwd
from geni_studio.verification.retro import scorecard
from geni_studio.web.app import app
from geni_studio.workflows.default import compile_graph, graph


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
        "geni_studio.config.registry.get_project_yaml",
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
    monkeypatch.setenv("GENI_STUDIO_GATE_TIMEOUT_SECONDS", "86400")
    st = svc.start(human_request="时限内", scenario_key="npu_operator")
    early = svc.status_dict(st.thread_id)
    assert early["phase"] == "awaiting_human"
    assert not early["values"].get("gate_timeout_recorded")
    assert early["values"].get("awaiting_since")

    monkeypatch.setenv("GENI_STUDIO_GATE_TIMEOUT_SECONDS", "0")
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
    assert "conversationSection" in text
    assert "展开全文" in text
    assert "renderMarkdown" in text
    assert 'id="swimRail"' in text
    assert ">运行状态</p>" in text
    assert "从目录打开" in text
    assert ">运行状态</span>" in text
    assert 'href="/workflow#new"' in text
    assert 'href="/help#overview"' in text
    assert 'href="/help#architecture"' in text
    assert 'href="/help#guide"' in text
    assert "安装步骤写在仓库的 README" in text
    assert 'id="btnContinueRun"' in text
    assert "这一轮在中途中断" in text
    assert 'id="flowNodeLoops"' in text
    assert "合规管理负责隐私、网络安全和知识产权" in text
    assert "入门指南" in text
    assert 'data-help-article="workflow"' in text
    assert "帮助只读。" in text
    assert 'id="flowHeading"' in text
    assert 'class="sidebar-svg"' in text
    assert "M88.7 223.8" in text
    assert 'class="project-modes"' not in text
    assert 'id="btnPickDirectory"' in text
    assert 'id="btnPickWorkspace"' in text
    assert 'id="btnDeleteProject"' in text
    assert 'id="btnOpenChosen"' not in text
    assert 'aria-label="选择目录"' in text
    assert 'id="btnSaveProject" appearance="outlined"' in text
    assert ">项目配置</span>" not in text
    assert 'aria-label="运行泳道"' in text
    assert "renderSwim" in text
    assert '{ id: "qa", role: "qa" }' in text
    assert "loadRoleTitles" in text
    assert 'run_start: "decision"' in text
    assert '{ id: "decision", label: "人类" }' in text
    assert "roundedOrth" in text
    assert "layoutSwimTimeline" in text
    assert "sideLink" in text
    assert "swim-decision" in text
    assert "/static/fork-sign.png" in text
    css = TestClient(app).get("/static/hitl.css").text
    assert ".swim-lane:nth-child(odd)" in css
    assert "is-compact" not in text
    assert 'className = "swim-state"' not in text
    assert 'addEventListener("conversation"' in text
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
    assert 'id="runProjectEmpty"' in text
    assert "/static/api-utils.js" in text
    assert "readFetchResponse" in text
    assert 'class="run-action-error"' in text
    assert "el.hidden = true" in text
    assert "hitlDockResize" in text
    assert "focusRunRailView" in text
    assert "armStartPoll" in text
    assert 'id="region-setup"' in text
    assert "inspect-body-run" in text
    assert "inspect-hitl-dock" in text
    assert ">保存草稿</wa-button>" in text
    todo_at = text.index('id="region-todo"')
    inspect_run_at = text.index("inspect-body-run")
    assert inspect_run_at < todo_at
    assert 'id="btnDeleteFlow" appearance="outlined" variant="danger" hidden' in text
    assert "载入非内置流程后，可以在复制和保存旁边删除。" in text
    save_at = text.index('id="flowSaveRow"')
    copy_at = text.index('id="btnCopyLoaded"')
    save_btn_at = text.index('id="btnSaveFlow"')
    delete_at = text.index('id="btnDeleteFlow"')
    assert save_at < copy_at < save_btn_at < delete_at
    assert "btnDeleteFlow" not in text[text.index('id="btnCopyFlow"'):save_at]
    script = TestClient(app).get("/static/workflow.js").text
    assert 'btnDeleteFlow").hidden = !created || builtin' in script
    assert 'btnCopyLoaded").hidden = !created' in script
    assert 'btnSaveFlow").hidden = !created || builtin' in script
    assert 'window.confirm("确定删除流程「" + title + "」（" + id + "）？删除后不能恢复。")' in script
    assert 'fetch("/api/workflows/" + encodeURIComponent(id), { method: "DELETE" })' in script
    assert "if (graph.builtin) return;" in script
    assert 'await enterOpen("", false);' in script
    assert 'showSaved("已删除 " + id + "。");' in script
    config = TestClient(app).get("/static/config.js").text
    assert "refreshWorkflowOptions" in config


def test_command_cwd_allows_a_subdirectory_and_rejects_a_sibling(tmp_path) -> None:
    from geni_studio.verification.command import TestCommandError

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
    from geni_studio.backends.runner import invoke_role
    from geni_studio.hitl.control import RunPaused, current_thread_id, request_pause
    from geni_studio.workspace.checkpoint import sqlite_checkpointer

    once = {"done": False}

    def wrapped(**kwargs):
        if not once["done"]:
            once["done"] = True
            request_pause(current_thread_id())
            raise RunPaused("本轮已暂停")
        return invoke_role(**kwargs)

    monkeypatch.setattr("geni_studio.backends.runner.invoke_role", wrapped)
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
