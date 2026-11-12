from pathlib import Path

import pytest
import yaml

from geni_studio.backends.runner import CapabilityError, invoke_role
from geni_studio.cli import cmd_show, main
from geni_studio.config.context import factory_root
from geni_studio.hitl.service import GraphRunService
from geni_studio.verification.acceptance import missing_acceptance_ids
from geni_studio.verification.retro import scorecard
from geni_studio.workflows.default import graph, run_builtin_node
from geni_studio.workspace.layout import prepare_run_layout


def test_missing_acceptance_blocks_qa():
    out = run_builtin_node(
        "qa",
        {
            "requirement_spec": "AC-1 必须有单测",
            "test_report": "未提及编号",
            "qa_status": "pass",
        }
    )
    assert out["qa_status"] == "fail"
    assert "AC-1" in out["qa_report"]
    assert missing_acceptance_ids(
        requirement_spec="AC-1",
        evidence=out["qa_report"],
    ) == []


def test_change_request_returns_to_requirement_gate():
    svc = GraphRunService(graph)
    st = svc.start(human_request="change", scenario_key="npu_operator")
    svc.submit_hitl(st.thread_id, gate_decision="approved", channel="web")
    svc._graph.update_state(
        svc._config(st.thread_id),
        {"change_request": "IMPACT: scope 缩小到一个算子"},
    )
    st = svc.submit_hitl(st.thread_id, gate_decision="approved", channel="web")
    assert st.awaiting_human is not None
    assert st.awaiting_human.gate_id == "gate_requirement_confirm"
    assert "尚未经过对应关卡批准" in (st.values.get("change_baseline_note") or "")


def test_cursor_backend_must_declare_run_commands_for_tester(monkeypatch):
    class _Bare:
        capabilities = frozenset({"text"})

        def complete(self, **kwargs: object) -> str:
            return "x"

    monkeypatch.setattr("geni_studio.backends.runner.get_default_backend", lambda: _Bare())
    with pytest.raises(CapabilityError, match="run_commands"):
        invoke_role(role_name="tester", user_prompt="u", stub_note="n")


def test_cli_config_roundtrip(tmp_path: Path):
    env = tmp_path / ".env"
    assert main(["--root", str(tmp_path), "config", "set", "GENI_STUDIO_BACKEND", "stub"]) == 0
    assert "GENI_STUDIO_BACKEND=stub" in env.read_text(encoding="utf-8")
    assert main(["--root", str(tmp_path), "config", "set", "CURSOR_API_KEY", "secret-value"]) == 0
    assert cmd_show(tmp_path) == 0


def test_scorecard_stays_pending_and_does_not_edit_roles():
    role = factory_root() / "roles" / "developer" / "role.md"
    before = role.read_text(encoding="utf-8")
    text = scorecard({"dev_retry_count": 1, "qa_status": "fail", "baseline_log": "x"})
    assert "提案状态：pending" in text
    assert "dev_retry_count=1" in text
    assert role.read_text(encoding="utf-8") == before


def test_factory_root_allowed_as_run_target(tmp_path: Path, monkeypatch) -> None:
    import subprocess

    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    monkeypatch.setattr("geni_studio.workspace.layout.factory_root", lambda: tmp_path)
    layout = prepare_run_layout(tmp_path, "factory-bootstrap")
    assert layout.target_root == tmp_path.resolve()


def test_project_yaml_selects_role_model(tmp_path: Path, monkeypatch):
    project = tmp_path / "projects" / "demo"
    project.mkdir(parents=True)
    (project / "project.yaml").write_text(
        "project_id: demo\nbackends:\n  developer:\n    model: composer-2\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("geni_studio.backends.runner.factory_root", lambda: tmp_path)
    from geni_studio.backends.cost import reset_project_id, set_project_id
    from geni_studio.backends.runner import model_for_role

    token = set_project_id("demo")
    try:
        assert model_for_role("developer") == "composer-2"
        from geni_studio.backends.runner import reset_role_models, set_role_models

        role_token = set_role_models({"developer": "gpt-run"})
        try:
            assert model_for_role("developer") == "gpt-run"
        finally:
            reset_role_models(role_token)
        assert model_for_role("developer") == "composer-2"
    finally:
        reset_project_id(token)


def test_worktree_test_command_is_evidence(tmp_path):
    from geni_studio.verification.command import run_test_command

    script = tmp_path / "check.py"
    script.write_text("print('AC-1 passed')\n", encoding="utf-8")
    result = run_test_command(
        {"workspace_path": str(tmp_path), "test_command": f"python3 {script}"}
    )
    assert result is not None
    assert result.returncode == 0
    assert "AC-1" in result.transcript


def test_disallowed_test_command_is_rejected():
    from geni_studio.verification.command import TestCommandError, resolve_test_command

    with pytest.raises(TestCommandError):
        resolve_test_command({"test_command": "bash -c echo"})


def test_test_command_must_stay_inside_the_worktree(tmp_path):
    from geni_studio.verification.command import (
        TestCommandError,
        assert_command_cwd,
        run_test_command,
    )

    workspace = tmp_path / "tree"
    workspace.mkdir()
    outside = tmp_path / "else"
    outside.mkdir()
    with pytest.raises(TestCommandError, match="工作树"):
        run_test_command({"test_command": "python3 -c pass"})
    with pytest.raises(TestCommandError, match="工作目录"):
        assert_command_cwd(outside, workspace)


def test_cli_hitl_approves_gate():
    from geni_studio.cli import main
    from geni_studio.hitl.service import GraphRunService
    from geni_studio.workflows.default import graph

    st = GraphRunService(graph).start(human_request="cli", scenario_key="npu_operator")
    assert main(["hitl", st.thread_id, "--decision", "approved", "--reply", "cli"]) == 0


def test_benchmark_before_and_after_command(tmp_path: Path):
    from geni_studio.config.context import factory_root
    from geni_studio.retro.benchmark import improved, run_task, write_score

    task = factory_root() / "evals" / "tasks" / "npu_mul.yaml"
    script = tmp_path / "check.py"
    script.write_text("print('AC-1 passed')\nprint('AC-2 passed')\n", encoding="utf-8")
    before = run_task(task)
    after = run_task(task, test_command=f"python3 {script}", workspace_path=str(tmp_path))
    assert before["acceptance_gap"] == ["AC-1", "AC-2"]
    assert after["acceptance_gap"] == []
    assert after["qa_status"] == "pass"
    assert improved(before, after) is True
    out = tmp_path / "after.json"
    write_score(after, out)
    saved = out.read_text(encoding="utf-8")
    assert '"acceptance_gap": []' in saved


def test_graph_reaches_final_gate_when_command_prints_acceptance(tmp_path: Path):
    script = tmp_path / "check.py"
    script.write_text("print('AC-1 passed')\n", encoding="utf-8")
    svc = GraphRunService(graph)
    st = svc.start(human_request="验收命令", scenario_key="npu_operator")
    svc._graph.update_state(
        svc._config(st.thread_id),
        {
            "requirement_spec": "AC-1 命令输出必须包含该编号。",
            "test_command": f"python3 {script}",
            "workspace_path": str(tmp_path),
        },
    )
    svc.submit_hitl(st.thread_id, gate_decision="approved", channel="test")
    st = svc.submit_hitl(st.thread_id, gate_decision="approved", channel="test")
    assert st.awaiting_human is not None
    assert st.awaiting_human.gate_id == "gate_final_delivery"
    report = st.values.get("test_report") or ""
    assert "AC-1" in report
    assert "exit=0" in report
    assert st.values.get("qa_status") == "pass"
    assert st.values.get("delivery_ready") is True


def test_unapproved_proposal_does_not_change_role(tmp_path: Path):
    from geni_studio.cli import main
    from geni_studio.evolution.proposals import ProposalError, apply_proposal

    role = tmp_path / "roles" / "developer" / "role.md"
    role.parent.mkdir(parents=True)
    role.write_text("# 程序员\n", encoding="utf-8")
    assert (
        main(
            [
                "--root",
                str(tmp_path),
                "proposal",
                "save",
                "p1",
                "--target",
                "roles/developer/role.md",
                "--summary",
                "补一句边界",
                "--body",
                "不直接对人类发消息。",
            ]
        )
        == 0
    )
    with pytest.raises(ProposalError, match="未经批准"):
        apply_proposal(tmp_path, "p1")
    assert role.read_text(encoding="utf-8") == "# 程序员\n"
    assert main(["--root", str(tmp_path), "proposal", "approve", "p1", "--evidence", "qa_status=pass"]) == 0
    assert main(["--root", str(tmp_path), "proposal", "apply", "p1"]) == 0
    assert "不直接对人类发消息" in role.read_text(encoding="utf-8")
    assert "p1" in (tmp_path / "evolution" / "ledger.md").read_text(encoding="utf-8")


def test_retro_writes_pending_proposal_without_editing_role(tmp_path: Path):
    from geni_studio.evolution.proposals import load_proposal
    worktree = tmp_path / ".geni_studio" / "worktrees" / "run1"
    worktree.mkdir(parents=True)
    role = tmp_path / "roles" / "process_owner" / "role.md"
    role.parent.mkdir(parents=True)
    role.write_text("# 流程负责人\n", encoding="utf-8")
    out = run_builtin_node("process_owner_retro", {"workspace_path": str(worktree), "dev_retry_count": 0, "qa_status": "pass"})
    assert "retro-run1" in out["process_proposals"]
    saved = load_proposal(tmp_path, "retro-run1")
    assert saved["status"] == "pending"
    assert role.read_text(encoding="utf-8") == "# 流程负责人\n"


def test_role_can_select_stub_backend(tmp_path: Path, monkeypatch):
    project = tmp_path / "projects" / "demo"
    project.mkdir(parents=True)
    (project / "project.yaml").write_text(
        "project_id: demo\nbackends:\n  developer:\n    backend: stub\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("geni_studio.backends.runner.factory_root", lambda: tmp_path)

    class _CursorLike:
        capabilities = frozenset({"text", "file_write", "shell", "mcp"})

        def complete(self, **kwargs: object) -> str:
            return "from-cursor"

    monkeypatch.setattr("geni_studio.backends.runner.get_default_backend", lambda: _CursorLike())
    from geni_studio.backends.cost import reset_project_id, set_project_id

    token = set_project_id("demo")
    try:
        text = invoke_role(role_name="developer", user_prompt="u", stub_note="按角色走 stub")
    finally:
        reset_project_id(token)
    assert text.startswith("[stub:developer]")
    assert "from-cursor" not in text


def test_self_improve_does_not_start_when_bridge_is_down():
    from geni_studio.workspace.self_improve import self_improve_block_reason

    assert self_improve_block_reason(False) == 2
    assert self_improve_block_reason(True) is None


def test_cli_status_shows_gate_and_cost(capsys):
    from geni_studio.cli import cmd_status
    from geni_studio.hitl.service import GraphRunService
    from geni_studio.workflows.default import graph

    st = GraphRunService(graph).start(human_request="看状态", scenario_key="npu_operator")
    assert cmd_status(st.thread_id) == 0
    out = capsys.readouterr().out
    assert "phase=awaiting_human" in out
    assert "gate=gate_requirement_confirm" in out
    assert "backend=stub" in out


def test_cli_answers_pm_clarification():
    svc = GraphRunService(graph)
    st = svc.start(human_request="澄清", scenario_key="npu_operator")
    svc.open_hitl(st.thread_id, kind="pm_clarification", questions=["范围？"], summary="请确认范围")
    assert main(["hitl", st.thread_id, "--reply", "仅 Mul 算子"]) == 0
    st = svc.status(st.thread_id)
    assert "仅 Mul 算子" in (st.values.get("requirement_spec") or "")
    assert st.awaiting_human is None or st.awaiting_human.kind != "pm_clarification"


def test_developer_prompt_limits_edits_to_worktree(monkeypatch):
    seen: dict[str, str] = {}

    def _fake(**kwargs: object) -> str:
        seen["user_prompt"] = str(kwargs.get("user_prompt") or "")
        return "ok"

    monkeypatch.setattr("geni_studio.backends.runner.invoke_role", _fake)
    run_builtin_node(
        "developer",
        {
            "human_request": "只改 README 的一行",
            "workspace_path": "/tmp/factory-worktree",
            "task_plan": "追加一行说明",
            "dev_retry_count": 0,
        }
    )
    assert "/tmp/factory-worktree" in seen["user_prompt"]
    assert "只改 README 的一行" in seen["user_prompt"]
    assert "不要合并" in seen["user_prompt"]


def test_self_improve_main_does_not_launch_graph_when_bridge_is_down(monkeypatch):
    import importlib.util

    path = factory_root() / "scripts" / "self_improve.py"
    spec = importlib.util.spec_from_file_location("self_improve_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "bridge_ready", lambda timeout=8: False)
    monkeypatch.setattr(
        module.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("不应启动整图")),
    )
    assert module.main() == 2


def test_persist_records_template_gaps(tmp_path: Path):
    from geni_studio.workspace.persist import persist_values

    persist_values(
        run_dir=tmp_path,
        thread_id="t1",
        phase="running",
        values={"requirement_spec": "只有一段没有模板标题的正文。"},
    )
    gaps = (tmp_path / "template_gaps.md").read_text(encoding="utf-8")
    assert "requirement_spec:" in gaps
    assert "1. 目的与范围" in gaps


def test_test_command_path_rejects_git_push():
    from geni_studio.verification.command import resolve_test_command
    from geni_studio.workspace.layout import WorkspaceError

    with pytest.raises(WorkspaceError, match="禁止推送"):
        resolve_test_command({"test_command": "git push origin main"})


def test_git_push_is_forbidden():
    from geni_studio.workspace.layout import WorkspaceError
    from geni_studio.workspace.policy import reject_remote_push

    with pytest.raises(WorkspaceError, match="禁止推送"):
        reject_remote_push(["git", "-C", "/tmp/wt", "push", "origin", "main"])


def test_second_writer_is_rejected(tmp_path: Path):
    from geni_studio.workspace.layout import WorkspaceError
    from geni_studio.workspace.policy import exclusive_write

    held = exclusive_write(tmp_path)
    held.__enter__()
    try:
        with pytest.raises(WorkspaceError, match="写入进行中"), exclusive_write(tmp_path):
            pass
    finally:
        held.__exit__(None, None, None)


def test_template_gap_lists_missing_section():
    from geni_studio.verification.template_check import missing_headings

    template = "## 1. 目的与范围\n## 2. 术语\n"
    assert missing_headings(template, "只有正文") == ["1. 目的与范围", "2. 术语"]
    assert missing_headings(template, "## 1. 目的与范围\n正文") == ["2. 术语"]


def test_benchmark_task_lists_acceptance_ids():
    data = yaml.safe_load((factory_root() / "evals" / "tasks" / "npu_mul.yaml").read_text(encoding="utf-8"))
    assert data["expect_acceptance_ids"] == ["AC-1", "AC-2"]


def test_architecture_change_returns_to_architecture_gate():
    svc = GraphRunService(graph)
    st = svc.start(human_request="arch change", scenario_key="npu_operator")
    svc.submit_hitl(st.thread_id, gate_decision="approved", channel="test")
    svc._graph.update_state(
        svc._config(st.thread_id),
        {"change_request": "IMPACT: architecture 调整任务边界"},
    )
    st = svc.submit_hitl(st.thread_id, gate_decision="approved", channel="test")
    assert st.awaiting_human is not None
    assert st.awaiting_human.gate_id == "gate_architecture_review"


def test_cli_run_reports_waiting_gate(capsys):
    from geni_studio.cli import main

    assert main(["run", "观测一下", "--scenario", "self_improve"]) == 0
    out = capsys.readouterr().out
    assert "thread_id=" in out
    assert "awaiting=gate" in out


def test_write_lock_records_only_current_owner(tmp_path: Path):
    from geni_studio.workspace.policy import _read_lock_owner, exclusive_write

    lock = tmp_path / ".geni_studio" / "write.lock"
    for owner in ("run-a", "run-b", "run-c"):
        with exclusive_write(tmp_path, owner=owner):
            lines = lock.read_text(encoding="utf-8").splitlines()
            assert len(lines) == 1
            assert _read_lock_owner(lock)["thread"] == owner
    assert lock.read_text(encoding="utf-8") == ""


def test_second_writer_waits_for_release(tmp_path: Path):
    import threading
    import time

    from geni_studio.workspace.policy import exclusive_write

    held = exclusive_write(tmp_path, owner="first")
    held.__enter__()
    threading.Timer(0.3, lambda: held.__exit__(None, None, None)).start()
    started = time.monotonic()
    with exclusive_write(tmp_path, owner="second", wait_seconds=5):
        waited = time.monotonic() - started
    assert 0.2 <= waited < 5
