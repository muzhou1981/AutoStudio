"""显式启用的真实 SDK 测试，会调用当前已认证账号的模型。"""

import os
import sys
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import MemorySaver

pytestmark = pytest.mark.skipif(
    os.environ.get("GENI_STUDIO_CODEX_LIVE_TEST") != "1",
    reason="真实模型测试需要显式设置 GENI_STUDIO_CODEX_LIVE_TEST=1",
)


def test_live_codex_resume(tmp_path, monkeypatch):
    from geni_studio.backends.codex_backend import CodexBackend
    from geni_studio.backends.cost import begin_cost_log, end_cost_log, take_cost_lines
    from geni_studio.hitl.control import bind_thread, unbind_thread
    from geni_studio.hitl.conversation import conversation_view
    from geni_studio.workspace.context import use_worktree

    monkeypatch.setattr("geni_studio.hitl.conversation.factory_root", lambda: tmp_path)
    monkeypatch.setenv("GENI_STUDIO_BACKEND", "codex")
    token = bind_thread("live-resume")
    cost = begin_cost_log()
    instruction = "This is a bounded SDK integration test. Do not use tools. Follow the user's exact reply format."
    try:
        with use_worktree(str(tmp_path)):
            first = CodexBackend(timeout_seconds=90).complete(
                role_name="compliance", system_prompt=instruction,
                user_prompt="Remember the nonce ORBIT_71832. Reply exactly SAVED.",
            )
            second = CodexBackend(timeout_seconds=90).complete(
                role_name="compliance", system_prompt=instruction,
                user_prompt="Return only the nonce from my previous message.",
            )
        assert first.strip() == "SAVED"
        assert second.strip() == "ORBIT_71832"
        turns = conversation_view("live-resume", "compliance", workspace_path=str(tmp_path))["turns"]
        assert len(turns) == 2
        assert turns[0]["events"][0]["agent_id"] == turns[1]["events"][0]["agent_id"]
        assert all(any(e["kind"] == "step" for e in t["events"]) for t in turns)
        assert all("input_tokens=" in line for line in take_cost_lines())
    finally:
        unbind_thread(token)
        end_cost_log(cost)


def test_live_workflow_writes_runs_tests_and_waits_for_human(tmp_path, monkeypatch):
    from geni_studio.hitl.service import GraphRunService
    from geni_studio.workflows.executable import compile_workflow

    monkeypatch.setenv("GENI_STUDIO_BACKEND", "codex")
    monkeypatch.setenv("GENI_STUDIO_WORKSPACE", "1")
    monkeypatch.setenv("GENI_STUDIO_TARGET_ROOT", str(tmp_path / "target"))
    monkeypatch.setenv("GENI_STUDIO_TEST_COMMAND", f"{sys.executable} -m unittest discover -p test_sdk_smoke.py -v")
    workflow = {"workflow_id": "live_smoke", "nodes": [
        {"id": "dev", "kind": "activity", "name": "实现", "role": "developer",
         "inputs": ["human_request"], "outputs": ["code_change"]},
        {"id": "test", "kind": "activity", "name": "测试", "role": "tester",
         "inputs": ["human_request", "code_change"], "outputs": ["test_report"]},
        {"id": "gate_final_delivery", "kind": "gate", "name": "确认", "role": "human", "decision": "approve"},
    ]}
    graph = compile_workflow(workflow, checkpointer=MemorySaver())
    service = GraphRunService(graph)
    result = service.start(human_request=(
        "This is a bounded integration test in a temporary git worktree. "
        "Create sdk_smoke.py containing add(a, b) that returns a+b, and test_sdk_smoke.py "
        "with unittest tests covering positive numbers, negatives and zero. "
        "Use only Python stdlib, no network, no git commit/push. "
        "Developer: create both files and run unittest. Tester: inspect them and run unittest again; "
        "correct them only if needed. Respond with the files changed and test outcome."
    ))
    assert result.phase == "awaiting_human"
    workspace = Path(result.values["workspace_path"])
    assert (workspace / "sdk_smoke.py").is_file()
    assert (workspace / "test_sdk_smoke.py").is_file()
    assert "exit=0" in result.values["test_report"]
    assert "OK" in result.values["test_report"]
    assert "backend=codex" in result.values["cost_ledger"]
    assert service.submit_hitl(result.thread_id, gate_decision="approved").phase == "completed"


def test_live_codex_stop_interrupts_active_command(tmp_path, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from geni_studio.backends.codex_backend import CodexBackend
    from geni_studio.hitl.control import (
        RunStopped,
        bind_thread,
        cancel_active_runs,
        clear_stop_request,
        request_stop,
        unbind_thread,
    )
    from geni_studio.hitl.conversation import append_step
    from geni_studio.workspace.context import use_worktree

    monkeypatch.setattr("geni_studio.hitl.conversation.factory_root", lambda: tmp_path)
    monkeypatch.setenv("GENI_STUDIO_BACKEND", "codex")
    started = threading.Event()

    def record(path, step):
        append_step(path, step)
        if step.get("type") == "item/started" and (step.get("message", {}).get("item") or {}).get("type") == "commandExecution":
            started.set()

    monkeypatch.setattr("geni_studio.hitl.conversation.append_step", record)

    def invoke():
        token = bind_thread("live-stop")
        try:
            with use_worktree(str(tmp_path)):
                return CodexBackend(timeout_seconds=90).complete(
                    role_name="developer",
                    system_prompt="You are testing cancellation. Follow the exact requested command, do not edit files or use network.",
                    user_prompt="Run the shell command sleep 30, wait for it to finish, then reply FINISHED. Do not skip the command.",
                )
        finally:
            unbind_thread(token)

    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(invoke)
        try:
            assert started.wait(60), "SDK did not start the test command"
            request_stop("live-stop")
            cancel_active_runs("live-stop")
            with pytest.raises(RunStopped):
                pending.result(timeout=15)
        finally:
            request_stop("live-stop")
            cancel_active_runs("live-stop")
    clear_stop_request("live-stop")
