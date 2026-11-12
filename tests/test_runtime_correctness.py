"""针对真实图调度、配置恢复与机器验证的回归测试。"""

import copy
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from langgraph.checkpoint.memory import MemorySaver

from geni_studio.config.context import ConfigError
from geni_studio.hitl.service import GraphRunService, HitlError
from geni_studio.workflows.default import compile_graph
from geni_studio.workflows.executable import compile_workflow


def activity(name, inputs=(), outputs=("code_change",), **extra):
    return {"id": name, "kind": "activity", "role": "compliance", "name": name,
            "inputs": list(inputs), "outputs": list(outputs), **extra}


@pytest.mark.parametrize("fails", [False, True])
def test_background_start_preserves_snapshot_and_reports_failure(monkeypatch, fails):
    monkeypatch.setenv("GENI_STUDIO_EXECUTOR", "thread")
    service = GraphRunService(compile_graph(checkpointer=MemorySaver()))
    entered, release = threading.Event(), threading.Event()
    invoke = service._invoke

    def delayed_invoke(thread_id, payload):
        entered.set()
        if not release.wait(5):
            raise TimeoutError("test did not release background start")
        if fails:
            raise ValueError("background start failed")
        invoke(thread_id, payload)

    monkeypatch.setattr(service, "_invoke", delayed_invoke)
    monkeypatch.setenv("GENI_STUDIO_CODEX_MODEL", "model-at-start")
    monkeypatch.setenv("GENI_STUDIO_CODEX_REASONING_EFFORT", "high")
    executor = service.executor()
    executor.start()
    try:
        tid, _initial = service.enqueue_start(
            human_request="后台启动回归", role_reasoning_efforts={"project_manager": "high"},
        )
        assert entered.wait(5)
        job = service.runtime_store().active_job(tid)
        assert job is not None and job.state == "running"
        provisional = service.view(tid)
        assert provisional["phase"] == "running"
        assert "config_snapshot_effective" not in provisional["values"]
        monkeypatch.setenv("GENI_STUDIO_CODEX_MODEL", "model-after-start")
        monkeypatch.setenv("GENI_STUDIO_CODEX_REASONING_EFFORT", "low")
        release.set()
        for _ in range(100):
            if service.runtime_store().active_job(tid) is None:
                break
            time.sleep(0.05)
        assert service.runtime_store().active_job(tid) is None
    finally:
        release.set()
        executor.stop()
    if fails:
        assert service.start_failure_message(tid) == "background start failed"
    else:
        status = service.status(tid)
        assert status.phase == "awaiting_human"
        assert status.values["config_snapshot_effective"]["_models"]["codex"] == "model-at-start"
        assert status.values["config_snapshot_effective"]["_codex_reasoning_effort"] == "high"
        assert status.values["role_reasoning_efforts"] == {"project_manager": "high"}
        assert service.start_failure_message(tid) is None


def test_start_job_first_checkpoint_without_next_nodes_stays_running(monkeypatch):
    service = GraphRunService(compile_graph(checkpointer=MemorySaver()))
    snap = SimpleNamespace(values={"human_request": "刚启动", "run_name": "r"}, next=(), created_at="")
    monkeypatch.setattr(service, "_bound", lambda _tid: SimpleNamespace(get_state=lambda _cfg: snap))
    monkeypatch.setattr(service, "_is_active", lambda _tid: True)
    job = SimpleNamespace(kind="start", state="running", note="",
                          payload={"human_request": "刚启动", "run_name": "r"})
    monkeypatch.setattr(service, "_job_active", lambda _tid: job)

    assert service.status("t").phase == "running"
    frame = service.view("t")
    assert frame["phase"] == "running"
    assert frame["rail"]["current"] != "end"
    assert {c["id"]: c["state"] for c in frame["rail"]["cells"]}.get("end") != "done"

    monkeypatch.setattr(service, "_job_active", lambda _tid: None)
    assert service.status("t").phase == "completed"


def parallel():
    return {"id": "p", "kind": "parallel", "name": "p", "fork_id": "p__fork", "join_id": "p__join",
            "branches": [
                {"id": "a", "name": "a", "steps": [activity("a1", parallel_id="p", branch_id="a")]},
                {"id": "b", "name": "b", "steps": [
                    activity("b1", parallel_id="p", branch_id="b"),
                    activity("b2", ["code_change"], ["task_plan"], parallel_id="p", branch_id="b"),
                    activity("b3", ["task_plan"], ["architecture_design"], parallel_id="p", branch_id="b"),
                ]},
            ]}


def test_unequal_parallel_branches_wait_and_read_local_outputs(monkeypatch):
    observed = []

    def invoke(**kw):
        prompt = kw["user_prompt"]
        name = prompt.splitlines()[0].split("：")[1]
        observed.append((name, prompt))
        if name == "b2":
            assert "code_change：\nb1-result" in prompt
        if name == "b3":
            assert "task_plan：\nb2-result" in prompt
        if name == "after":
            assert "b3-result" in prompt
        return name + "-result"

    monkeypatch.setattr("geni_studio.backends.runner.invoke_role", invoke)
    workflow = {"nodes": [parallel(), activity("after", ["architecture_design"], ["qa_report"])]}
    original = copy.deepcopy(workflow)
    graph = compile_workflow(workflow, checkpointer=MemorySaver())
    final = graph.invoke({"code_change": "stale-global"}, {"configurable": {"thread_id": "unequal"}})
    assert final["qa_report"] == "after-result"
    assert [name for name, _ in observed].count("after") == 1
    assert workflow == original


@pytest.mark.parametrize("change", ["gate", "loop", "nested"])
def test_reject_unsupported_parallel(change):
    node = parallel()
    first = node["branches"][0]["steps"][0]
    if change == "gate":
        first["kind"] = "gate"
    elif change == "loop":
        first["returns_to"] = "a1"
    else:
        node["branches"][0]["steps"] = [parallel()]
    with pytest.raises(ConfigError, match="并行支路"):
        compile_workflow({"nodes": [node]}, checkpointer=MemorySaver())


def test_pause_after_completed_call_keeps_node_output(monkeypatch):
    from geni_studio.hitl.control import current_thread_id, request_pause

    calls = []

    def invoke(**kw):
        calls.append(kw["stub_note"])
        if kw["stub_note"] == "first":
            request_pause(current_thread_id())
        return kw["stub_note"]

    monkeypatch.setattr("geni_studio.backends.runner.invoke_role", invoke)
    graph = compile_workflow({"nodes": [activity("first"), activity("second", outputs=["qa_report"])]}, checkpointer=MemorySaver())
    service = GraphRunService(graph)
    paused = service.start(human_request="pause")
    assert paused.phase == "paused"
    assert paused.values["code_change"] == "first"
    assert paused.next_nodes == ("second",)
    assert service.resume(paused.thread_id).phase == "completed"
    assert calls == ["first", "second"]


def test_pause_does_not_hide_real_exception(monkeypatch):
    from geni_studio.hitl.control import (
        clear_pause_request,
        current_thread_id,
        request_pause,
    )

    def invoke(**kw):
        request_pause(current_thread_id())
        raise ValueError("broken")

    monkeypatch.setattr("geni_studio.backends.runner.invoke_role", invoke)
    service = GraphRunService(compile_workflow({"nodes": [activity("first")]}, checkpointer=MemorySaver()))
    try:
        with pytest.raises(ValueError, match="broken"):
            service.start(human_request="test", thread_id="pause-error")
        assert service.status("pause-error").phase == "interrupted"
    finally:
        clear_pause_request("pause-error")


def test_restart_uses_saved_workflow_not_modified_file(tmp_path, monkeypatch):
    from test_subgraph_parallel import _patch, _root

    _root(tmp_path)
    _patch(monkeypatch, tmp_path)
    folder = tmp_path / "workflows" / "sample"
    folder.mkdir(parents=True)
    path = folder / "workflow.yaml"
    path.write_text("""workflow_id: sample
title: snapshot
nodes:
- {id: start, kind: start, name: start, role: human}
- {id: draft, kind: activity, name: draft, role: project_manager}
- {id: gate, kind: gate, name: approve, role: human, decision: approve}
- {id: done, kind: activity, name: original, role: developer}
- {id: end, kind: end, name: end, role: human}
""")
    saver = MemorySaver()
    service = GraphRunService(compile_graph(saver))
    waiting = service.start(human_request="freeze", scenario_key="demo", project_id="bound")
    path.write_text(path.read_text().replace("name: original", "name: changed"))
    restarted = GraphRunService(compile_graph(saver))
    completed = restarted.submit_hitl(waiting.thread_id, gate_decision="approved")
    assert "original" in completed.values["code_change"]
    assert "changed" not in completed.values["code_change"]
    assert "workflow_definition" not in restarted.status_dict(waiting.thread_id)["values"]


def test_reject_concurrent_hitl_for_same_run(monkeypatch):
    from geni_studio.hitl.transaction import run_mutation

    entered, release = threading.Event(), threading.Event()

    class Service:
        @run_mutation
        def mutate(self, thread_id):
            entered.set()
            assert release.wait(3)

    service = Service()
    with ThreadPoolExecutor() as pool:
        future = pool.submit(service.mutate, "same-run")
        assert entered.wait(2)
        try:
            with pytest.raises(HitlError, match="另一个请求"):
                service.mutate("same-run")
        finally:
            release.set()
        future.result()


def test_machine_evidence_controls_test_outcome(monkeypatch):
    from geni_studio.verification.command import verified_report

    monkeypatch.setattr("geni_studio.verification.command.run_test_command", lambda state: SimpleNamespace(returncode=0, transcript="exit=0"))
    assert verified_report({}, "report", "fail")[1] == "pass"
    assert verified_report({}, "report", "fail", claim_binding=True)[1] == "fail"
    monkeypatch.setattr("geni_studio.verification.command.run_test_command", lambda state: SimpleNamespace(returncode=1, transcript="exit=1"))
    assert verified_report({}, "STATUS: pass")[1] == "fail"
    monkeypatch.setattr("geni_studio.verification.command.run_test_command", lambda state: None)
    monkeypatch.setattr("geni_studio.backends.runner.backend_for_role", lambda role: object())
    assert verified_report({}, "STATUS: pass")[1] == "fail"


def test_workspace_probe_does_not_overwrite_existing_file(tmp_path):
    from geni_studio.config.connectivity import _workspace

    existing = tmp_path / ".geni_studio_write_probe"
    existing.write_text("important")
    assert _workspace(str(tmp_path))[0] == "ok"
    assert existing.read_text() == "important"


def test_acceptance_ids_do_not_match_prefixes():
    from geni_studio.verification.acceptance import missing_acceptance_ids

    assert missing_acceptance_ids(requirement_spec="AC-1 AC-10", evidence="AC-10") == ["AC-1"]


def test_models_are_scoped_to_selected_backend(monkeypatch):
    from geni_studio.backends.base import factory_default_model

    monkeypatch.setenv("GENI_STUDIO_BACKEND", "cursor")
    monkeypatch.setenv("GENI_STUDIO_DEFAULT_MODEL", "cursor-legacy")
    monkeypatch.delenv("GENI_STUDIO_CODEX_MODEL", raising=False)
    assert factory_default_model("codex") == ""
    monkeypatch.setenv("GENI_STUDIO_CODEX_MODEL", "codex-only")
    assert factory_default_model("codex") == "codex-only"


def test_gate_never_implicitly_approves():
    from geni_studio.hitl.gate import apply_gate_node

    for state in ({}, {"gate_decision": "unknown"}):
        with pytest.raises(ValueError, match="明确"):
            apply_gate_node("gate", state)
    assert apply_gate_node("gate", {"gate_decision": "approved"})["gate_decision"] is None


def test_legacy_selected_run_is_readable_but_not_resumable():
    saver = MemorySaver()
    graph = compile_graph(saver)
    cfg = {"configurable": {"thread_id": "legacy-selected"}}
    graph.update_state(cfg, {"human_request": "legacy", "workflow_id": "removed-flow"}, as_node="tester_testability")
    service = GraphRunService(graph)
    status = service.status("legacy-selected")
    assert status.phase == "awaiting_human"
    with pytest.raises(HitlError, match="缺少流程定义快照"):
        service.submit_hitl("legacy-selected", gate_decision="approved")
    assert not service.status("legacy-selected").values.get("baseline_log")


def test_equal_cost_lines_from_separate_calls_are_preserved():
    service = GraphRunService(compile_graph(MemorySaver()))
    status = service.start(human_request="cost")
    service._append_costs(status.thread_id, ["same-call-usage"])
    service._append_costs(status.thread_id, ["same-call-usage"])
    assert service.status(status.thread_id).values["cost_ledger"].count("same-call-usage") == 2


def _modern_node() -> str | None:
    import os
    import subprocess
    from pathlib import Path

    candidates = [Path(d) / "node" for d in os.environ.get("PATH", "").split(os.pathsep)]
    candidates += sorted((Path.home() / ".nvm/versions/node").glob("*/bin/node"), reverse=True)
    for node in candidates:
        if not node.is_file():
            continue
        version = subprocess.run([str(node), "--version"], check=False, capture_output=True, text=True).stdout.strip()
        if version.startswith("v") and int(version[1:].split(".")[0]) >= 18:
            return str(node)
    return None


def test_config_runtime_frontend():
    import subprocess
    from pathlib import Path

    node = _modern_node()
    if node is None:
        pytest.skip("Node.js >= 18 unavailable")
    subprocess.run([node, str(Path(__file__).with_name("config_runtime_regression.cjs"))], check=True, timeout=10)


def test_conversation_frontend_shows_summaries_only():
    import subprocess
    from pathlib import Path

    node = _modern_node()
    if node is None:
        pytest.skip("Node.js >= 18 unavailable")
    subprocess.run([node, str(Path(__file__).with_name("conversation_regression.cjs"))], check=True, timeout=10)


def test_api_key_probe_does_not_change_local_sdk_login(monkeypatch):
    import urllib.error

    from geni_studio.config.connectivity import probe_openai_api_key

    def rejected(request, **kwargs):
        raise urllib.error.HTTPError(request.full_url, 401, "Unauthorized", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", rejected)
    status, detail = probe_openai_api_key("test-only-secret")
    assert status == "fail"
    assert "test-only-secret" not in detail


def test_observation_does_not_mark_in_progress_mutation_interrupted():
    from geni_studio.hitl.transaction import run_mutation

    service = GraphRunService(compile_graph(MemorySaver()))
    started = service.start(human_request="observe")
    cfg = service._config(started.thread_id)
    service._graph.update_state(cfg, {"gate_decision": "approved"}, as_node="gate_requirement_confirm")
    entered, release = threading.Event(), threading.Event()

    @run_mutation
    def hold(self, thread_id):
        entered.set()
        assert release.wait(3)

    with ThreadPoolExecutor() as pool:
        future = pool.submit(hold, service, started.thread_id)
        assert entered.wait(2)
        try:
            assert service.status_dict(started.thread_id)["phase"] == "running"
            assert not service.status(started.thread_id).values.get("run_interrupted")
        finally:
            release.set()
        future.result()
