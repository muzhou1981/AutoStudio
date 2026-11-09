from geni_studio.config.env_loader import apply_env_file


def test_apply_env_file_setdefault(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("GENI_STUDIO_TEST_ENV_LOADER=from_file\n", encoding="utf-8")
    monkeypatch.delenv("GENI_STUDIO_TEST_ENV_LOADER", raising=False)
    apply_env_file(root=tmp_path)
    import os

    assert os.environ.get("GENI_STUDIO_TEST_ENV_LOADER") == "from_file"
