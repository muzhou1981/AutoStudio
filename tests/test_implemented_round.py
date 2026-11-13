"""已实现功能的补充用例：快照、列表、超时、检视数据、命令边界、复盘和暂停续跑。"""

from __future__ import annotations

import re
from pathlib import Path

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
    project = Path(__file__).resolve().parents[1] / "projects" / "_example" / "project.yaml"
    original = project.read_text(encoding="utf-8")
    st = svc.start(human_request="项目快照", project_id="_example", run_name="快照轮")
    frozen = str(st.values.get("config_snapshot_project") or "")
    assert frozen == original
    assert "scenario_key: npu_operator" in str(st.values.get("config_snapshot_scenario") or "")
    monkeypatch.setattr(
        "geni_studio.config.registry.get_project_yaml",
        lambda *args, **kwargs: "project_id: _example\ntitle: 后来改过\n",
    )
    again = svc.status(st.thread_id)
    assert again.values.get("config_snapshot_project") == frozen
    assert "后来改过" not in str(again.values.get("config_snapshot_project"))


def test_run_list_filters_by_project_and_reports_retry_limit(svc: GraphRunService, example_retry_limit) -> None:
    st = svc.start(human_request="列表项目", project_id="_example", run_name="项目列表")
    matched = svc.list_runs(project_id="_example")
    assert any(row["thread_id"] == st.thread_id and row["run_name"] == "项目列表" for row in matched)
    assert all(row["project_id"] == "_example" for row in matched)
    other = svc.list_runs(project_id="helloworld")
    assert all(row["thread_id"] != st.thread_id for row in other)
    data = svc.status_dict(st.thread_id)
    assert data["limits"]["max_dev_retries"] == example_retry_limit
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
    client = TestClient(app)
    text = client.get("/").text + client.get("/static/hitl.js").text
    assert 'id="runPhaseFilter"' in text
    assert ">Run列表</span>" in text
    assert 'value="all"' in text
    assert "runListSeq" in text
    assert "conversationSection" in text
    assert "function artifactCard(" not in text
    assert 'textContent = "产物"' not in text
    assert "renderMarkdown" in text
    assert 'id="swimRail"' in text
    assert ">运行状态</p>" in text
    assert "从目录打开" in text
    assert 'href="/#region-rail"' not in text
    assert 'href="/#region-todo"' not in text
    assert 'href="/workflow#new"' in text
    assert 'href="/help#overview"' in text
    assert 'href="/help#architecture"' in text
    assert 'href="/help#guide"' in text
    assert "安装步骤写在仓库的 README" in text
    assert 'id="btnContinueRun"' in text
    assert "这一轮在中途中断" in text
    assert 'id="flowNodeMenuShell"' in text and 'id="flowInspectEdge"' in text
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
    assert 'id="btnOpenRole"' not in text
    assert 'id="rolePick"' in text
    assert text.index('id="rolePick"') < text.index('id="roleTitle"')
    role_js = TestClient(app).get("/static/role.js?v=20261112-role-pick-top").text
    assert 'rolePick").addEventListener("change"' in role_js
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
    assert 'if (kind === "gate") name.append(window.geniIcons.decisionIcon(cell.state === "done"));' in text
    assert "fork-sign" not in text
    assert "function syncGateItems(ah)" in text and "payload.item_decisions" in text
    assert "其余全部通过" in text and "还差 " in text
    html = TestClient(app).get("/").text
    assert 'id="gateItems"' in html and 'id="flowGateItemsBox"' in html and 'id="btnAddGateItem"' in html
    flow = TestClient(app).get("/static/workflow.js").text
    assert "function renderGateItemsEditor(node, readOnly)" in flow and '"items", "pass_rule"' in flow
    icons = TestClient(app).get("/static/icons.js")
    assert icons.status_code == 200 and "decisionIcon" in icons.text
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
    assert 'inspectSection("调用次数"' not in text
    assert "未碰到开发重试上限" not in text
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
    assert 'id="region-setup"' not in text
    assert 'id="btnStart" variant="brand">启动</wa-button>\n                <wa-button id="btnSaveRun"' in text
    # 交付目标与启动在右栏下方，只在看「启动」时出现；中栏底部只留续跑、暂停与停止
    dock = text[text.index('id="region-todo"'):text.index('id="dockTodo"')]
    assert 'id="req"' in dock and 'id="btnStart"' in dock and 'id="btnAttach"' in dock
    controls = text[text.index('id="region-controls"'):text.index("</main>", text.index('id="region-controls"'))]
    assert 'id="btnStop"' in controls and 'id="btnPause"' in controls and 'id="btnStart"' not in controls
    assert "function syncDock(cell, data)" in text and "if ($(\"dockTodo\").hidden) viewRailCell(restingCellId);" in text
    banner = text[text.index('id="banner"'):text.index('id="gateIdleHint"')]
    assert 'id="btnReplyAttach"' in banner and 'id="replyAttachList"' in banner
    assert "payload.attachments = replyAttachments.map" in text
    assert 'id="pendingAlert"' in text and 'id="stopConfirm"' in text
    assert 'class="sidebar-foot"' in text and "theme-fab" not in text
    assert "inspect-body-run" in text
    assert "inspect-hitl-dock" in text
    assert "原始状态" not in text
    assert 'id="out"' not in text
    assert '$("out")' not in text
    assert "这一步还没有指定 " not in text
    # 口径 A：保留分组标题与「增加」，仅去掉未选项空态提示；后端空目录提示仍在
    assert 'label.textContent = title;' in text
    assert 'button.textContent = "增加";' in text
    assert '"后端没有列出 " + title + "。"' in text
    assert ">保存 Run 配置</wa-button>" in text
    assert ">保存草稿</wa-button>" not in text
    todo_at = text.index('id="region-todo"')
    inspect_run_at = text.index("inspect-body-run")
    assert inspect_run_at < todo_at
    # 流程编辑：删除流程移入「更多」并在原位确认，不与保存相邻；只保留一个复制入口；不再显示原文 YAML
    assert 'id="flowDeleteConfirm"' in text and 'id="btnDeleteFlow" variant="danger">删除流程</wa-button>' in text
    assert "删除在选择框右侧的「更多」里" in text
    toolbar = text[text.index('<div class="flow-head-row">'):text.index('id="flowEditor"')]
    assert 'id="btnSaveFlow" variant="brand"' in toolbar and "btnDeleteFlow" not in toolbar
    assert 'id="flowToolbar"' not in text
    assert 'id="btnCopyLoaded"' not in text and 'id="flowRaw"' not in text and 'id="flowYaml"' not in text
    assert 'class="flow-composer"' not in text
    script = TestClient(app).get("/static/workflow.js").text
    assert '$("btnSaveFlow").hidden = on || !created || builtin' in script
    assert "!event.isComposing && event.keyCode !== 229" in script
    assert 'title: "删除流程…", danger: true, onPick: openDeleteConfirm, disabled: inUse' in script
    assert "删除后不能恢复。" in script
    assert 'fetch("/api/workflows/" + encodeURIComponent(id), { method: "DELETE" })' in script
    assert "/raw" not in script
    # 回退与不通过都画成虚线，从右侧绕回左侧；连线中点可插入节点；节点设置用级联菜单
    assert 'edges.push({ from: node.id, to: node.reject_to, kind: "reject" })' in script
    assert "function loopLink(a, b, y)" in script and "function insertButton(a, b, index)" in script
    assert "function edgeHandle(edge)" in script and "function nodeMenuRows(node)" in script
    assert "if (!id || graph.builtin) return;" in script
    assert 'await enterOpen("", false);' in script
    assert 'showSaved("已删除 " + id + "。");' in script
    # 删除等结果提示在切换页面、切换编辑档或点开选择框后消失
    assert '$("flowPick").addEventListener("wa-show", () => showSaved(""));' in script
    assert 'window.clearWorkflowNotice = () => showSaved("");' in script
    config = TestClient(app).get("/static/config.js").text
    assert "refreshWorkflowOptions" in config


def test_run_prompt_has_no_example_placeholder() -> None:
    client = TestClient(app)
    text = client.get("/").text + client.get("/static/hitl.js").text
    start = text.index('id="req"')
    tag = text[start:text.index(">", start)]
    assert 'label="描述本轮交付目标"' in tag
    assert "placeholder=" not in tag
    assert "例如：为 npu_operator 场景实现 Mul 算子，含单测与性能基线" not in text
    assert 'id="runName" label="Run 命名" placeholder="先选择项目"' in text
    assert "project.disabled = bound" in text
    assert 'placeholder="补充范围说明或驳回原因…"' in text


def test_role_model_settings_live_in_the_inspect_panel() -> None:
    page = TestClient(app).get("/").text
    script = TestClient(app).get("/static/hitl.js").text
    config = TestClient(app).get("/static/config.js").text
    assert 'id="roleModelHint"' not in page
    assert 'id="roleModelList"' not in page
    assert "角色模型与推理强度</p>" not in page
    assert "roleGroup.appendChild(roleModelSection(cell, data, notes));" in script
    assert "stepGroup.appendChild(nodeToolColumn(cell, data, notes));" in script
    assert 'settingsGroup("角色属性", "settings-group-role"' in script
    assert 'settingsGroup("步骤属性", "settings-group-step"' in script
    assert "个节点共用" not in script
    assert "remove.innerHTML = TRASH_ICON;" in script
    assert "del.innerHTML = TRASH_ICON;" in script
    assert "nodeToolsSection" not in script
    settings_at = script.index("if (isActivityCell(cell)) inspectParts.push(inspectSettings(cell, data));")
    assert settings_at < script.index("inspectParts.push(conversationSection(cell.id, session));")
    assert "runRoleDefaultsError = \"读不到角色的模型设置：\"" in script
    assert "Skill 和 MCP 不能再改" not in script
    assert "以上设置不能再改" not in script
    assert "模型与推理强度不能再改" not in script
    css = TestClient(app).get("/static/hitl.css").text
    assert ".role-model-block { display: contents; }" in css
    assert "@container (max-width: 44rem)" not in css
    assert ".inspect-settings-columns {\n  display: grid;\n  grid-template-columns: repeat(2, minmax(0, 1fr));" in css
    assert 'const ROLE_PREFS_URL = "/api/config/user/role-model-prefs";' in script
    assert "restoreConversationScroll(body, nodeId);" in script
    assert 'body.addEventListener("scroll", (ev) => {' in script
    assert "void loadRolePrefs();" in script
    assert 'chip.className = "role-menu-chip";' in script
    assert 'subRow("推理强度", text, "effort")' in script and 'subRow("模型",' in script
    assert 'row.addEventListener("mouseenter", () => showFlyout(row, page, false));' in script
    assert "function placeFlyout(wrap, row, fly)" in script
    assert 'search.placeholder = "搜索模型";' in script
    assert 'document.createElement("wa-switch")' in script
    assert 'notes.push({ text: runModelDetails[s.backend] || "读不到模型列表。" });' in script
    assert "window.__backendModelsDetail" in config
    assert "留空表示沿用配置里的默认模型" not in page + config
    assert "这一轮的选择不影响其它 Run" not in page + config


def test_hitl_reading_fills_parent_width() -> None:
    client = TestClient(app)
    text = client.get("/").text + client.get("/static/hitl.js").text
    todo = text[text.index('id="region-todo"'):text.index('id="gateIdleHint"')]
    assert 'id="hitlReading" class="hitl-reading"' in todo
    assert 'id="hitlChoiceActions"' in todo
    stylesheet = re.search(r'href="(/static/hitl\.css\?v=[^\"]+)"', text)
    assert stylesheet is not None
    assert "skillPickMenu" in text
    assert "skill-pick-shell" in text
    assert "closeSkillPick" in text
    assert "toolAddSelect" not in text
    assert "if (add) list.lastElementChild.appendChild(add);" in text
    assert 'subRow("推理强度", "由 Auto 决定", "effort", { disabled: true })' in text
    assert "Auto 模型由 Cursor 自动选择，不能指定推理强度。\"" not in text
    css = TestClient(app).get(stylesheet.group(1)).text
    assert "wa-color-surface-raised" in css
    assert "wa-color-neutral-fill-normal" in css
    assert "inspect-run-scroll .status-empty" in css
    assert "white-space: nowrap" in css
    assert '["状态", STATE_LABEL' not in text
    assert "这一步还没有会话" not in text
    assert "renderChoiceSurvey" in text or "hitl-choice-grid" in text
    assert 'class="run-copy"' in text or "run-copy" in text
    css = TestClient(app).get("/static/hitl.css").text
    start = css.index(".hitl-reading {")
    block = css[start:css.index("}", start)]
    assert "width: 100%" in block
    assert "max-width: 100%" in block
    assert "min-width: 0" in block
    assert "65ch" not in block


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


def test_inspect_sections_have_no_redundant_headings() -> None:
    client = TestClient(app)
    script = client.get("/static/hitl.js").text
    assert 'heading.textContent = "会话"' not in script
    assert 'heading.textContent = "Skill 与 MCP"' not in script
    assert 'section.setAttribute("aria-label", "会话")' in script
    assert 'strip.setAttribute("aria-label", "本步骤设置")' in script
    assert 'heading.textContent = "本步骤设置"' not in script


def test_mcp_is_listed_read_only_on_the_config_page_not_per_step() -> None:
    client = TestClient(app)
    page = client.get("/").text
    script = client.get("/static/hitl.js").text
    config = client.get("/static/config.js").text
    agent = page[page.index('id="region-agent"'):page.index('id="region-feishu"')]
    assert 'id="mcpList"' in agent and "<wa-select" not in agent[agent.index('id="mcpField"'):]
    assert '"mcp", "MCP"' not in script and "mcp:" not in script
    assert "/api/config/tools?" in config and 'params.set("project_id"' in config


def test_run_page_ignores_stale_responses_and_stops_push_off_route() -> None:
    script = TestClient(app).get("/static/hitl.js").text
    assert "data.thread_id !== $(\"thread\").value.trim()) return;" in script
    assert "refreshQueued" in script and "if (refreshing) return;" not in script
    assert "syncConversationThread(tid)" in script and "rememberConversation(payload, tid)" in script
    assert "if (leavingRun) stopPoll();" in script and "onRunRoute()" in script
    assert '"paused", "interrupted", "awaiting_human"' in script
    assert "nodeToolError = { node: cell.id" in script


def test_run_page_new_steps_redraw_only_the_conversation() -> None:
    script = TestClient(app).get("/static/hitl.js").text
    assert "if (rememberConversation(payload, tid)) refreshConversation(payload.node);" in script
    assert "rememberConversation(JSON.parse(ev.data), tid) && lastStatus) renderInspect" not in script
    # 推送与补拉两处都按同一个进行中判断渲染，不再一处展开、一处收起。
    assert script.count("formatConversation(payload)") == 0
    assert script.count("conversationLive(") >= 3
    assert "followBottom(body, () => fillConversation(body, nodeId, html));" in script
    assert "if (renderedConversation.get(body) === html) return;" in script


def test_run_page_lanes_scroll_when_they_do_not_fit() -> None:
    client = TestClient(app)
    script = client.get("/static/hitl.js").text
    css = client.get("/static/hitl.css").text
    shared = client.get("/static/shared.css").text
    assert "rail-compact" not in script and "rail-compact" not in css
    assert 'grid.style.minWidth = Math.ceil(grid.clientWidth + need - width) + "px";' in script
    assert ".swim-scroll {\n  overflow-x: auto;" in css
    assert "const STATE_MARK = {" in script and 'id="railLegend"' in client.get("/").text
    assert ".workspace-inspect { grid-column: 2 / -1; }" in shared
    assert 'current.kind === "end"' in script


def test_workflow_editor_has_history_check_usage_and_trail() -> None:
    client = TestClient(app)
    text = client.get("/").text
    script = client.get("/static/workflow.js").text
    head = text[text.index('<div class="flow-head-row">'):text.index('id="flowEditor"')]
    assert 'id="btnFlowUndo"' in head and 'id="btnFlowRedo"' in head and 'id="btnFlowCheck"' in head
    assert 'id="flowTrail"' in text and 'id="flowProblems"' in text and 'id="flowUsage"' in text
    assert "function recordHistory()" in script and "function stepHistory(delta)" in script
    assert 'if (key !== "z" && key !== "y") return;' in script
    assert '"/check"' in script and '"/usage"' in script
    assert "[...trail, loadedId]" in script and 'params.get("trail")' in script
    # 只写名称的角色默认产物与缺省的输入输出，保存与检查时都不能被改写
    assert "item.plain && !item.template" in script and "function roleDefaultOutput(node, item)" in script
    assert "body: JSON.stringify(graph)" not in script
    assert 'id="flowVersions"' in text and "async function loadVersion(item)" in script
    assert '"/versions/" + item.version' in script
    assert 'id="flowStatsNote"' in text and 'showStats ? "隐藏运行数据" : "显示运行数据"' in script
    assert '"/stats"' in script and "function markStats()" in script
    assert "function branchReturnRow(node, step, earlier, locked)" in script
    assert "function joinRow(node, locked)" in script and '{ id: "pick", label: "择一（两路对照）" }' in script
    run_script = client.get("/static/hitl.js").text
    assert 'id="branchChoice"' in text and "function syncBranchChoice(options)" in run_script
    assert "payload.branch_choice = $(\"branchChoice\").value;" in run_script
    assert '"采用「" + entry.picked + "」"' in run_script
