"""飞书 lark-cli 配置与通知逻辑测试。"""

from auto_studio.hitl.feishu_config import (
    load_feishu_hitl_config,
    resolve_lark_backend,
)
from auto_studio.hitl.feishu_notify import format_gate_message, hitl_page_url


def test_resolve_lark_backend_default_lark_cli(tmp_path, monkeypatch):
    monkeypatch.setattr("auto_studio.hitl.feishu_config.factory_root", lambda: tmp_path)
    assert resolve_lark_backend(tmp_path) == "lark_cli"


def test_resolve_lark_backend_env_bot_when_app_id(tmp_path, monkeypatch):
    monkeypatch.setattr("auto_studio.hitl.feishu_config.factory_root", lambda: tmp_path)
    (tmp_path / ".env").write_text("LARK_APP_ID=cli_x\n", encoding="utf-8")
    assert resolve_lark_backend(tmp_path) == "env_bot"


def test_load_feishu_hitl_from_example():
    cfg = load_feishu_hitl_config("_example")
    assert cfg is None


def test_load_feishu_hitl_from_env(tmp_path, monkeypatch):
    monkeypatch.setattr("auto_studio.hitl.feishu_config.factory_root", lambda: tmp_path)
    monkeypatch.setenv("AUTO_STUDIO_FEISHU_NOTIFY_OPEN_ID", "ou_test")
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
