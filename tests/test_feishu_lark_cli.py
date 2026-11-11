"""飞书 lark-cli 配置与通知逻辑测试。"""

from geni_studio.hitl.feishu_config import (
    load_feishu_hitl_config,
    resolve_lark_backend,
)
from geni_studio.hitl.feishu_notify import format_gate_message, hitl_page_url
from geni_studio.hitl.lark_cli_client import _user_identity_from_auth


def test_lark_cli_path_from_nvm_layout(tmp_path, monkeypatch):
    from geni_studio.hitl import lark_cli_client

    fake_home = tmp_path / "home"
    bin_dir = fake_home / ".nvm" / "versions" / "node" / "v24.0.0" / "bin"
    bin_dir.mkdir(parents=True)
    exe = bin_dir / "lark-cli"
    exe.write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
    exe.chmod(0o755)
    monkeypatch.setattr(lark_cli_client.Path, "home", staticmethod(lambda: fake_home))
    monkeypatch.delenv("GENI_STUDIO_LARK_CLI_PATH", raising=False)
    monkeypatch.delenv("LARK_CLI_PATH", raising=False)
    monkeypatch.setattr(lark_cli_client.shutil, "which", lambda _name: None)
    assert lark_cli_client.lark_cli_path() == str(exe.resolve())


def test_lark_cli_path_explicit_env(tmp_path, monkeypatch):
    from geni_studio.hitl import lark_cli_client

    exe = tmp_path / "custom-lark-cli"
    exe.write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
    exe.chmod(0o755)
    monkeypatch.setenv("GENI_STUDIO_LARK_CLI_PATH", str(exe))
    monkeypatch.setattr(lark_cli_client.shutil, "which", lambda _name: None)
    assert lark_cli_client.lark_cli_path() == str(exe.resolve())


def test_user_identity_from_auth_json():
    data = {
        "identities": {
            "user": {"openId": "ou_abc", "userName": "张三"},
        }
    }
    assert _user_identity_from_auth(data) == ("ou_abc", "张三")


def test_resolve_lark_backend_default_lark_cli(tmp_path, monkeypatch):
    monkeypatch.setattr("geni_studio.hitl.feishu_config.factory_root", lambda: tmp_path)
    assert resolve_lark_backend(tmp_path) == "lark_cli"


def test_resolve_lark_backend_env_bot_when_app_id(tmp_path, monkeypatch):
    monkeypatch.setattr("geni_studio.hitl.feishu_config.factory_root", lambda: tmp_path)
    monkeypatch.delenv("GENI_STUDIO_LARK_BACKEND", raising=False)
    (tmp_path / ".env").write_text("LARK_APP_ID=cli_x\n", encoding="utf-8")
    assert resolve_lark_backend(tmp_path) == "env_bot"


def test_env_bot_sends_without_putting_the_secret_in_the_message(monkeypatch):
    from geni_studio.hitl.feishu_open_api import send_interactive_via_tenant

    seen = {"bodies": [], "urls": []}

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            if len(seen["bodies"]) > 1:
                return b'{"code":0}'
            return b'{"code":0,"tenant_access_token":"tenant-token"}'

    def _open(request, timeout=15):
        seen["urls"].append(request.full_url)
        if request.data:
            seen["bodies"].append(request.data.decode("utf-8"))
        return _Response()

    monkeypatch.setattr("geni_studio.hitl.feishu_open_api.urllib.request.urlopen", _open)
    send_interactive_via_tenant(
        app_id="cli_app",
        app_secret="super-secret",
        content_json='{"schema":"2.0"}',
        chat_id="oc_chat",
    )
    assert "super-secret" in seen["bodies"][0]
    assert "super-secret" not in seen["bodies"][1]
    assert "tenant-token" not in seen["bodies"][1]
    assert any("messages?receive_id_type=chat_id" in url for url in seen["urls"])
    assert "super-secret" not in "".join(seen["urls"])


def test_session_binding_survives_a_new_read(tmp_path, monkeypatch):
    from geni_studio.hitl.feishu_session import (
        register_awaiting_thread,
        resolve_thread_id,
    )

    monkeypatch.setattr(
        "geni_studio.hitl.feishu_session.sessions_path",
        lambda: tmp_path / "feishu_sessions.json",
    )
    register_awaiting_thread(thread_id="older", chat_id="oc_keep")
    register_awaiting_thread(thread_id="newer", chat_id="oc_keep")
    assert resolve_thread_id(chat_id="oc_keep") == "newer"
    assert (tmp_path / "feishu_sessions.json").is_file()


def test_load_feishu_hitl_from_example(tmp_path, monkeypatch):
    monkeypatch.setattr("geni_studio.hitl.feishu_config.factory_root", lambda: tmp_path)
    monkeypatch.delenv("GENI_STUDIO_FEISHU_NOTIFY_OPEN_ID", raising=False)
    cfg = load_feishu_hitl_config("_example")
    assert cfg is None


def test_load_feishu_hitl_from_env(tmp_path, monkeypatch):
    monkeypatch.setattr("geni_studio.hitl.feishu_config.factory_root", lambda: tmp_path)
    monkeypatch.setenv("GENI_STUDIO_FEISHU_NOTIFY_OPEN_ID", "ou_test")
    cfg = load_feishu_hitl_config("")
    assert cfg is not None
    assert cfg.notify_open_id == "ou_test"


def test_hitl_page_url_uses_thread_id():
    assert hitl_page_url("http://127.0.0.1:8765/", "abc") == (
        "http://127.0.0.1:8765/?thread_id=abc"
    )


def test_format_gate_message():
    text = format_gate_message(
        thread_id="tid-1",
        summary="需求确认",
        gate_id="gate_requirement_confirm",
        web_url="http://127.0.0.1:8766/?thread=tid-1",
    )
    assert "tid-1" in text
    assert "需求确认" in text
    assert "待批复" in text
    assert "8766" in text
