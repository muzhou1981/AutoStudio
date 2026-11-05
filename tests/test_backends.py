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
