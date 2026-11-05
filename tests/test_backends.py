from auto_studio.backends.base import StubBackend, get_default_backend


def test_stub_backend():
    b = StubBackend()
    out = b.complete(role_name="pm", system_prompt="s", user_prompt="u")
    assert "pm" in out


def test_default_backend_is_stub_without_env():
    b = get_default_backend()
    assert isinstance(b, StubBackend)
