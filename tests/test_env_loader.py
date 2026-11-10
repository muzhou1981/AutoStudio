import os

from geni_studio.config.env_loader import (
    apply_env_file,
    bootstrap_env,
    sync_env_secrets_to_dotenv,
)


def test_apply_env_file_setdefault(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("GENI_STUDIO_TEST_ENV_LOADER=from_file\n", encoding="utf-8")
    monkeypatch.delenv("GENI_STUDIO_TEST_ENV_LOADER", raising=False)
    apply_env_file(root=tmp_path)
    assert os.environ.get("GENI_STUDIO_TEST_ENV_LOADER") == "from_file"


def test_sync_cursor_key_from_environ_when_dotenv_empty(tmp_path, monkeypatch):
    monkeypatch.setattr("geni_studio.config.env_loader.factory_root", lambda: tmp_path)
    monkeypatch.setenv("CURSOR_API_KEY", "shell-secret")
    (tmp_path / ".env").write_text("CURSOR_API_KEY=\n", encoding="utf-8")
    written = sync_env_secrets_to_dotenv(root=tmp_path)
    assert written == ["CURSOR_API_KEY"]
    assert "CURSOR_API_KEY=shell-secret" in (tmp_path / ".env").read_text(encoding="utf-8")


def test_sync_cursor_key_skips_when_dotenv_has_value(tmp_path, monkeypatch):
    monkeypatch.setattr("geni_studio.config.env_loader.factory_root", lambda: tmp_path)
    monkeypatch.setenv("CURSOR_API_KEY", "shell-secret")
    (tmp_path / ".env").write_text("CURSOR_API_KEY=file-secret\n", encoding="utf-8")
    written = sync_env_secrets_to_dotenv(root=tmp_path)
    assert written == []
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "CURSOR_API_KEY=file-secret\n"


def test_bootstrap_env_prefers_shell_over_empty_dotenv(tmp_path, monkeypatch):
    monkeypatch.setattr("geni_studio.config.env_loader.factory_root", lambda: tmp_path)
    monkeypatch.setenv("CURSOR_API_KEY", "shell-secret")
    (tmp_path / ".env").write_text("CURSOR_API_KEY=\n", encoding="utf-8")
    bootstrap_env(root=tmp_path)
    assert os.environ.get("CURSOR_API_KEY") == "shell-secret"
    assert "CURSOR_API_KEY=shell-secret" in (tmp_path / ".env").read_text(encoding="utf-8")
