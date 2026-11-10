"""使用实际 SDK 类型检查适配契约；只替换进程/网络客户端。"""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

sdk = pytest.importorskip("openai_codex")
from openai_codex.generated.v2_all import (
    ItemCompletedNotification,
    ModelListResponse,
    ThreadTokenUsageUpdatedNotification,
    TurnCompletedNotification,
)
from openai_codex.models import Notification

from geni_studio.backends.codex_backend import CodexBackend, list_codex_models
from geni_studio.backends.runner import CapabilityError, invoke_role


def events(status="completed", phase="final_answer", text="ok"):
    yield Notification("item/completed", ItemCompletedNotification.model_validate({
        "threadId": "thread1", "turnId": "turn1", "completedAtMs": 1,
        "item": {"type": "agentMessage", "id": "msg1", "text": text, "phase": phase},
    }))
    counts = {"inputTokens": 4, "outputTokens": 6, "totalTokens": 10,
              "cachedInputTokens": 0, "reasoningOutputTokens": 0}
    yield Notification("thread/tokenUsage/updated", ThreadTokenUsageUpdatedNotification.model_validate({
        "threadId": "thread1", "turnId": "turn1", "tokenUsage": {"last": counts, "total": counts},
    }))
    yield Notification("turn/completed", TurnCompletedNotification.model_validate({
        "threadId": "thread1", "turn": {"id": "turn1", "status": status, "items": [], "itemsView": "full"},
    }))


@pytest.fixture
def fake_client(monkeypatch, tmp_path):
    from geni_studio.workspace.context import use_worktree

    monkeypatch.delenv("GENI_STUDIO_CODEX_MODEL", raising=False)
    monkeypatch.delenv("GENI_STUDIO_DEFAULT_MODEL", raising=False)
    monkeypatch.setattr("geni_studio.hitl.conversation.factory_root", lambda: tmp_path)

    calls = SimpleNamespace(starts=[], resumes=[], prompts=[], closed=0, interrupted=False,
                            status="completed", phase="final_answer", account=True, hook=None)

    class Handle:
        id = "turn1"

        def stream(self):
            if calls.hook:
                calls.hook()
            yield from events(calls.status, calls.phase)

        def interrupt(self):
            calls.interrupted = True

    class Thread:
        id = "thread1"

        def turn(self, prompt):
            calls.prompts.append(prompt)
            return Handle()

    class Client:
        def thread_start(self, **kwargs):
            calls.starts.append(kwargs)
            return Thread()

        def thread_resume(self, thread_id, **kwargs):
            calls.resumes.append((thread_id, kwargs))
            return Thread()

        def models(self):
            return ModelListResponse.model_validate({"data": [{
                "id": "catalog-row", "model": "gpt-test", "displayName": "GPT Test",
                "description": "test", "hidden": False, "isDefault": True,
                "supportedReasoningEfforts": [], "defaultReasoningEffort": "low",
            }]})

        def account(self):
            return SimpleNamespace(requires_openai_auth=True, account=object() if calls.account else None)

        def close(self):
            calls.closed += 1

    @contextmanager
    def opened(**kwargs):
        client = Client()
        try:
            yield client
        finally:
            client.close()

    monkeypatch.setattr("geni_studio.backends.codex_backend._open_codex", opened)
    calls.client_type = Client
    with use_worktree(str(tmp_path)):
        yield calls


def test_role_instructions_and_thread_resumption(fake_client):
    backend = CodexBackend()
    for prompt in ("第一次", "第二次"):
        assert backend.complete(role_name="developer", system_prompt="角色定义", user_prompt=prompt) == "ok"
    assert len(fake_client.starts) == 1
    assert len(fake_client.resumes) == 1
    assert fake_client.starts[0]["developer_instructions"] == "角色定义"
    assert fake_client.starts[0]["sandbox"] is sdk.Sandbox.workspace_write
    assert fake_client.starts[0]["approval_mode"] is sdk.ApprovalMode.deny_all
    assert "model" not in fake_client.starts[0]
    assert fake_client.closed == 2


def test_explicit_model_and_real_sdk_usage(fake_client):
    from geni_studio.backends.cost import begin_cost_log, end_cost_log, take_cost_lines

    token = begin_cost_log()
    try:
        CodexBackend().complete(role_name="developer", system_prompt="s", user_prompt="u", model="gpt-test")
        lines = take_cost_lines()
    finally:
        end_cost_log(token)
    assert fake_client.starts[0]["model"] == "gpt-test"
    assert any("input_tokens=4 output_tokens=6" in line for line in lines)


@pytest.mark.parametrize("status", ["failed", "interrupted", "inProgress"])
def test_only_successful_terminal_turn_returns_text(fake_client, status):
    fake_client.status = status
    with pytest.raises(RuntimeError, match="没有完成"):
        CodexBackend().complete(role_name="developer", system_prompt="s", user_prompt="u")
    assert fake_client.closed == 1


def test_commentary_is_not_final_response(fake_client):
    fake_client.phase = "commentary"
    with pytest.raises(RuntimeError, match="正文"):
        CodexBackend().complete(role_name="architect", system_prompt="s", user_prompt="u")


def test_codex_model_identifier_is_model_not_catalog_id(fake_client, monkeypatch):
    monkeypatch.setenv("GENI_STUDIO_BACKEND", "codex")
    from geni_studio.backends.base import get_default_backend

    assert isinstance(get_default_backend(), CodexBackend)
    assert list_codex_models()["models"] == [{"id": "gpt-test", "label": "GPT Test"}]


def test_actual_role_invocation_resumes_across_backend_instances(fake_client, monkeypatch):
    from geni_studio.hitl.control import bind_thread, unbind_thread

    monkeypatch.setattr("geni_studio.backends.runner._role_config", lambda *args: {"backend": "codex"})
    token = bind_thread("resume-run")
    try:
        for _ in range(2):
            assert invoke_role(role_name="developer", user_prompt="u", stub_note="x") == "ok"
    finally:
        unbind_thread(token)
    assert len(fake_client.starts) == 1
    assert len(fake_client.resumes) == 1


def test_missing_codex_sdk_never_falls_back(monkeypatch):
    monkeypatch.setenv("GENI_STUDIO_BACKEND", "codex")
    monkeypatch.setattr("geni_studio.backends.codex_backend.try_codex_backend", lambda: None)
    from geni_studio.backends.base import get_default_backend

    with pytest.raises(RuntimeError, match="openai-codex"):
        get_default_backend()


def test_unknown_role_backend_is_rejected(monkeypatch):
    monkeypatch.setattr("geni_studio.backends.runner._role_config", lambda *args: {"backend": "coedx"})
    with pytest.raises(CapabilityError, match="未知"):
        invoke_role(role_name="developer", user_prompt="u", stub_note="x")


def test_real_workspace_required(monkeypatch):
    from geni_studio.workspace.context import use_worktree

    with use_worktree(""), pytest.raises(RuntimeError, match="工作区"):
        CodexBackend().complete(role_name="developer", system_prompt="s", user_prompt="u")


def test_role_sandbox_and_identity(fake_client):
    backend = CodexBackend()
    backend.complete(role_name="compliance", system_prompt="one", user_prompt="u")
    backend.complete(role_name="compliance", system_prompt="two", user_prompt="u")
    assert len(fake_client.starts) == 2
    assert fake_client.starts[0]["sandbox"] is sdk.Sandbox.read_only
    with pytest.raises(ValueError, match="需要写"):
        CodexBackend(sandbox="read-only").complete(role_name="developer", system_prompt="s", user_prompt="u")


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_invalid_timeout(timeout):
    with pytest.raises(ValueError):
        CodexBackend(timeout_seconds=timeout)


def test_stop_calls_sdk_interrupt(fake_client):
    from geni_studio.hitl.control import (
        RunStopped,
        bind_thread,
        cancel_active_runs,
        clear_stop_request,
        request_stop,
        unbind_thread,
    )

    def stop():
        request_stop("stop-run")
        cancel_active_runs("stop-run")

    fake_client.hook = stop
    token = bind_thread("stop-run")
    try:
        with pytest.raises(RunStopped):
            CodexBackend().complete(role_name="architect", system_prompt="s", user_prompt="u")
        assert fake_client.interrupted
    finally:
        clear_stop_request("stop-run")
        unbind_thread(token)


def test_probe_requires_account(fake_client):
    from geni_studio.config.connectivity import probe_codex

    fake_client.account = False
    assert probe_codex("")[0] == "fail"
    fake_client.account = True
    status, detail = probe_codex("")
    assert status == "ok"
    assert "尚未验证实际推理" in detail


def test_login_failure_closes_client(monkeypatch):
    from geni_studio.backends.codex_backend import _open_codex

    closed = []

    class Client:
        def login_api_key(self, key):
            raise RuntimeError("login failed")

        def close(self):
            closed.append(True)

    monkeypatch.setattr(sdk, "Codex", Client)
    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    with pytest.raises(RuntimeError, match="login failed"), _open_codex():
        pass
    assert closed


def test_timeout_closes_client_and_unblocks(monkeypatch):
    import threading

    from geni_studio.backends.codex_backend import _open_codex

    closed = threading.Event()
    monkeypatch.setattr(sdk, "Codex", lambda: SimpleNamespace(close=closed.set))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(TimeoutError), _open_codex(timeout=0.02):
        assert closed.wait(2)
