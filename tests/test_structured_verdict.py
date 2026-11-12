"""结构化结论驱动评审、测试、QA 与回退（C1、C2、C3、D2）。"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import MemorySaver

from geni_studio.hitl.service import GraphRunService
from geni_studio.verification.acceptance import acceptance_sources, machine_accepted_ids
from geni_studio.verification.verdict import (
    judge,
    parse_change_request,
    parse_verdict,
    split_outputs,
)
from geni_studio.workflows.default import compile_graph


def _verdict(status: str, **ac: str) -> str:
    return "```verdict\n" + json.dumps({"status": status, "ac": ac}) + "\n```"


class _FakeBackend:
    capabilities = frozenset({"text", "file_read", "file_write", "shell", "mcp"})

    def __init__(self, reply: Callable[[str, str], str]) -> None:
        self.reply = reply
        self.prompts: list[tuple[str, str]] = []

    def complete(self, *, role_name: str, system_prompt: str, user_prompt: str, model: str | None) -> str:
        self.prompts.append((role_name, user_prompt))
        return self.reply(role_name, user_prompt)


@pytest.fixture
def real_backend(monkeypatch: pytest.MonkeyPatch):
    def install(reply: Callable[[str, str], str]) -> _FakeBackend:
        backend = _FakeBackend(reply)
        monkeypatch.setattr("geni_studio.backends.runner.backend_for_role", lambda role, project_id="": backend)
        return backend

    return install


def test_verdict_parser_and_fail_closed() -> None:
    assert parse_verdict("正文") is None
    ok = parse_verdict("正文\n" + _verdict("pass", **{"AC-1": "pass"}))
    assert ok is not None and ok.passed and ok.ac == {"AC-1": "pass"}
    bad = parse_verdict("```verdict\n{status: pass}\n```")
    assert bad is not None and not bad.passed and bad.source == "invalid"
    assert judge("已覆盖 AC-1", simulated=False).status == "fail"
    assert judge("已覆盖 AC-1", simulated=False).source == "missing"
    assert judge("x", simulated=True, preset="fail").status == "fail"
    assert judge("x\nSTATUS: fail", simulated=True).status == "fail"


def test_acceptance_needs_verdict_or_command_not_mention() -> None:
    spec = "AC-1 AC-2"
    report = "## 测试命令\n```\npython3 check.py\nexit=0\nAC-1 ok\n```"
    assert machine_accepted_ids(report) == {"AC-1"}
    assert machine_accepted_ids(report.replace("exit=0", "exit=1")) == set()
    sources = acceptance_sources(
        requirement_spec=spec,
        verdicts=[parse_verdict(_verdict("pass", **{"AC-2": "pass"}))],
        test_report=report,
    )
    assert sources == {"AC-1": "验证命令输出", "AC-2": "结论块"}
    mention_only = acceptance_sources(requirement_spec=spec, verdicts=[None], test_report="AC-1 AC-2 都提到了")
    assert mention_only == {"AC-1": "", "AC-2": ""}


def test_change_request_and_output_split() -> None:
    body = "改了 a.py\n```change_request\n{\"impact\": \"scope\", \"reason\": \"缩小范围\"}\n```"
    assert parse_change_request(body)[0] == "scope"
    parts = split_outputs(body, ["code_change", "change_request"], optional=frozenset({"change_request"}))
    assert parts["code_change"] == body
    assert "缩小范围" in parts["change_request"]
    assert split_outputs("只改代码", ["code_change", "change_request"], optional=frozenset({"change_request"})) == {
        "code_change": "只改代码",
        "change_request": "",
    }


def test_reviewer_without_verdict_fails_and_feeds_developer(real_backend) -> None:
    from geni_studio.workflows.default import run_builtin_node

    real_backend(lambda role, prompt: "看起来不错，AC-1 已实现。")
    out = run_builtin_node("code_reviewer", {"code_change": "改动"})
    assert out["review_status"] == "fail"
    assert "缺少结构化结论块" in out["review_report"]
    backend = real_backend(lambda role, prompt: "修好了")
    run_builtin_node("developer", {"task_plan": "t", "return_feedback": out["return_feedback"], "dev_retry_count": 1})
    role, prompt = backend.prompts[-1]
    assert role == "developer"
    assert "需要修复的问题" in prompt and "AC-1 已实现" in prompt


def test_reviewer_fail_verdict_returns_to_developer_with_report(real_backend, tmp_path: Path) -> None:
    script = tmp_path / "check.py"
    script.write_text("print('AC-1 passed')\n", encoding="utf-8")
    reviews = {"n": 0}

    def reply(role: str, prompt: str) -> str:
        if role == "project_manager" and "交付报告" not in prompt:
            return "## 验收标准\nAC-1 输出编号"
        if role == "code_reviewer":
            reviews["n"] += 1
            if reviews["n"] == 1:
                return "缺少边界检查 BOUNDARY-42\n" + _verdict("fail")
            return "通过\n" + _verdict("pass")
        if role in {"tester", "qa"}:
            return "验证完成\n" + _verdict("pass", **{"AC-1": "pass"})
        return f"{role} 产出"

    backend = real_backend(reply)
    svc = GraphRunService(compile_graph(MemorySaver()))
    st = svc.start(human_request="评审回退", scenario_key="npu_operator")
    svc._graph.update_state(
        svc._config(st.thread_id),
        {"test_command": f"python3 {script}", "workspace_path": str(tmp_path)},
    )
    svc.submit_hitl(st.thread_id, gate_decision="approved", channel="test")
    st = svc.submit_hitl(st.thread_id, gate_decision="approved", channel="test")
    assert st.awaiting_human is not None and st.awaiting_human.gate_id == "gate_final_delivery"
    dev_prompts = [prompt for role, prompt in backend.prompts if role == "developer"]
    assert len(dev_prompts) == 2
    assert "BOUNDARY-42" not in dev_prompts[0]
    assert "BOUNDARY-42" in dev_prompts[1]
    assert st.values["review_status"] == "pass"
    assert st.values["qa_status"] == "pass"
    assert st.values["delivery_ready"] is True
    assert not st.values.get("return_feedback")


def test_developer_change_request_returns_to_requirement_gate(real_backend) -> None:
    def reply(role: str, prompt: str) -> str:
        if role == "developer":
            return "计划不可行\n```change_request\n{\"impact\": \"scope\", \"reason\": \"只做 Mul\"}\n```"
        return f"{role} 产出"

    real_backend(reply)
    svc = GraphRunService(compile_graph(MemorySaver()))
    st = svc.start(human_request="变更", scenario_key="npu_operator")
    svc.submit_hitl(st.thread_id, gate_decision="approved", channel="test")
    st = svc.submit_hitl(st.thread_id, gate_decision="approved", channel="test")
    assert st.awaiting_human is not None
    assert st.awaiting_human.gate_id == "gate_requirement_confirm"
    assert st.values["change_impact"] == "scope"
    assert "只做 Mul" in st.values["change_baseline_note"]
    assert not st.values.get("change_request")


def test_qa_mentions_without_verdict_do_not_pass(real_backend) -> None:
    from geni_studio.workflows.default import run_builtin_node

    real_backend(lambda role, prompt: "AC-1 已验证通过。\n" + _verdict("pass"))
    out = run_builtin_node("qa", {"requirement_spec": "AC-1", "test_report": "AC-1 提到了", "test_status": "pass"})
    assert out["qa_status"] == "fail"
    assert "AC-1" in out["return_feedback"]


def _compiled_root(tmp_path: Path) -> None:
    for role, outputs in {
        "developer": "[code_change, change_request]",
        "code_reviewer": "[review_report]",
    }.items():
        (tmp_path / "roles" / role).mkdir(parents=True)
        (tmp_path / "roles" / role / "role.md").write_text(
            f"---\nname: {role}\ntitle: {role}\ninputs: [code_change]\noutputs: {outputs}\n---\n",
            encoding="utf-8",
        )


def test_compiled_review_without_verdict_returns_with_feedback(real_backend, tmp_path: Path) -> None:
    from geni_studio.workflows.executable import compile_workflow, resolve_executable

    _compiled_root(tmp_path)
    workflow = resolve_executable(
        {
            "workflow_id": "w",
            "nodes": [
                {"id": "dev", "kind": "activity", "name": "开发", "role": "developer", "returns_to": ""},
                {"id": "rev", "kind": "activity", "name": "评审", "role": "code_reviewer", "returns_to": "dev"},
            ],
        },
        root=tmp_path,
    )
    reviews = {"n": 0}

    def reply(role: str, prompt: str) -> str:
        if role == "code_reviewer":
            reviews["n"] += 1
            return "缺少空指针检查 NULL-7" if reviews["n"] == 1 else "通过\n" + _verdict("pass")
        return "改了代码"

    backend = real_backend(reply)
    graph = compile_workflow(workflow, checkpointer=MemorySaver())
    out = graph.invoke({"human_request": "x"}, {"configurable": {"thread_id": "t"}})
    dev_prompts = [prompt for role, prompt in backend.prompts if role == "developer"]
    assert len(dev_prompts) == 2
    assert "NULL-7" in dev_prompts[1]
    assert out["return_counts"]["rev"] == 1
    assert out["change_request"] == ""
    assert out["code_change"] == "改了代码"
    assert not out.get("return_feedback")
