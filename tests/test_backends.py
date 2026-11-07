import os

from auto_studio.backends.base import StubBackend, get_default_backend


def test_stub_backend():
    b = StubBackend()
    out = b.complete(role_name="pm", system_prompt="s", user_prompt="u")
    assert "pm" in out


def test_default_backend_is_stub_without_env(monkeypatch):
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    monkeypatch.delenv("AUTO_STUDIO_BACKEND", raising=False)
    b = get_default_backend()
    assert isinstance(b, StubBackend)


def test_default_backend_uses_cursor_when_api_key(monkeypatch):
    monkeypatch.setenv("CURSOR_API_KEY", "test-key")
    monkeypatch.delenv("AUTO_STUDIO_BACKEND", raising=False)
    monkeypatch.setenv("AUTO_STUDIO_CURSOR_VERIFY", "0")

    class _FakeCursor:
        def complete(self, **kwargs: object) -> str:
            return "cursor-ok"

    monkeypatch.setattr(
        "auto_studio.backends.cursor_backend.CursorBackend",
        _FakeCursor,
    )
    b = get_default_backend()
    assert b.complete(role_name="x", system_prompt="s", user_prompt="u") == "cursor-ok"


def test_auto_studio_backend_stub_overrides_key(monkeypatch):
    monkeypatch.setenv("CURSOR_API_KEY", "test-key")
    monkeypatch.setenv("AUTO_STUDIO_BACKEND", "stub")
    b = get_default_backend()
    assert isinstance(b, StubBackend)


def test_cursor_complete_records_token_usage(monkeypatch):
    monkeypatch.setenv("CURSOR_API_KEY", "test-key")
    monkeypatch.setenv("AUTO_STUDIO_CURSOR_VERIFY", "0")

    class _Usage:
        input_tokens = 3
        output_tokens = 5

    class _Run:
        def __init__(self) -> None:
            self._terminal_result = type("Result", (), {"usage": _Usage()})()

        def text(self) -> str:
            return "ok"

    class _Agent:
        def send(self, prompt: str, options=None) -> _Run:
            return _Run()

    class _Client:
        def create_agent(self, opts, api_key=None):
            return _Agent()

    monkeypatch.setattr("cursor_sdk._client._default_client", lambda: _Client())
    from auto_studio.backends.cost import begin_cost_log, end_cost_log, take_cost_lines
    from auto_studio.backends.cursor_backend import CursorBackend

    token = begin_cost_log()
    try:
        assert CursorBackend().complete(role_name="developer", system_prompt="s", user_prompt="u") == "ok"
        lines = take_cost_lines()
    finally:
        end_cost_log(token)
    assert any("input_tokens=3" in line and "output_tokens=5" in line for line in lines)


def test_role_md_is_sent_once_per_live_agent(monkeypatch):
    monkeypatch.setenv("CURSOR_API_KEY", "test-key")
    monkeypatch.setenv("AUTO_STUDIO_CURSOR_VERIFY", "0")
    prompts: list[str] = []

    class _Run:
        def text(self) -> str:
            return "ok"

    class _Agent:
        def send(self, prompt: str, options=None) -> _Run:
            prompts.append(prompt)
            if options is not None and getattr(options, "on_step", None):
                options.on_step({"type": "assistantMessage", "message": "一段回复"})
            return _Run()

    class _Client:
        def create_agent(self, opts, api_key=None):
            return _Agent()

    monkeypatch.setattr("cursor_sdk._client._default_client", lambda: _Client())
    from auto_studio.backends.cursor_backend import CursorBackend

    backend = CursorBackend()
    backend.complete(role_name="architect", system_prompt="角色定义", user_prompt="写设计")
    backend.complete(role_name="architect", system_prompt="角色定义", user_prompt="写计划")
    backend.complete(role_name="developer", system_prompt="程序员定义", user_prompt="写代码")
    assert prompts[0].startswith("角色定义")
    assert "写设计" in prompts[0]
    assert prompts[1] == "## 本轮任务\n\n写计划"
    assert "角色定义" not in prompts[1]
    assert prompts[2].startswith("程序员定义")


def test_uppercase_proxy_is_copied_for_the_bridge(monkeypatch):
    from auto_studio.backends.cursor_backend import ensure_lowercase_proxy

    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:8080")
    monkeypatch.delenv("https_proxy", raising=False)
    ensure_lowercase_proxy()
    assert os.environ["https_proxy"] == "http://proxy.example:8080"
    assert os.environ["NODE_USE_ENV_PROXY"] == "1"
