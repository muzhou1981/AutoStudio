import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from geni_studio.config import user_prefs
from geni_studio.config.context import ConfigError
from geni_studio.web.app import app

URL = "/api/config/user/role-model-prefs"


def test_prefs_are_saved_per_role_and_model(tmp_path: Path) -> None:
    assert user_prefs.role_model_prefs() == {}
    prefs = user_prefs.set_role_model_pref(
        "developer", "cursor", "gpt-5.5", {"effort": "High", "fast": "on", "params": {"context": "272k"}}
    )
    assert prefs == {"developer": {"cursor:gpt-5.5": {"effort": "high", "fast": "on", "params": {"context": "272k"}}}}
    user_prefs.set_role_model_pref("developer", "cursor", "", {"fast": "off"})
    user_prefs.set_role_model_pref("tester", "codex", "full", {"effort": "default"})
    saved = json.loads((tmp_path / "user_config.json").read_text(encoding="utf-8"))
    assert saved["version"] == 1
    assert saved["role_model_prefs"]["developer"]["cursor:default"] == {"fast": "off"}
    assert saved["role_model_prefs"]["tester"] == {"codex:full": {"effort": "default"}}

    prefs = user_prefs.set_role_model_pref("developer", "cursor", "gpt-5.5", {})
    assert prefs["developer"] == {"cursor:default": {"fast": "off"}}, "全为默认时删去该项"
    prefs = user_prefs.set_role_model_pref("developer", "cursor", "", {"effort": "", "params": {"context": ""}})
    assert "developer" not in prefs, "角色没有记忆时删去角色"


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (("developer", "Cursor!", "gpt-5.5", {}), "后端标识无效"),
        (("developer", "cursor", "bad model", {}), "模型标识无效"),
        (("", "cursor", "gpt-5.5", {"effort": "high"}), "角色标识"),
        (("developer", "cursor", "gpt-5.5", {"effort": "turbo"}), "reasoning_effort"),
        (("developer", "cursor", "gpt-5.5", {"fast": "maybe"}), "fast"),
        (("developer", "cursor", "gpt-5.5", {"params": {"thinking": "on"}}), "模型参数只能是 context"),
        (("developer", "cursor", "gpt-5.5", {"model": "x"}), "只能包含"),
    ],
)
def test_invalid_prefs_are_rejected(args: tuple, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        user_prefs.set_role_model_pref(*args)


def test_unreadable_entries_are_dropped_but_corrupt_file_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "user_config.json"
    path.write_text(json.dumps({"role_model_prefs": {
        "developer": {"cursor:gpt-5.5": {"effort": "high"}, "cursor:gpt-5.5x": {"effort": "turbo"}, "bad": {}},
        "tester": "oops",
    }, "other": {"kept": True}}), encoding="utf-8")
    assert user_prefs.role_model_prefs() == {"developer": {"cursor:gpt-5.5": {"effort": "high"}}}
    user_prefs.set_role_model_pref("tester", "cursor", "grok-4.7", {"effort": "low"})
    assert json.loads(path.read_text(encoding="utf-8"))["other"] == {"kept": True}, "其它用户配置原样保留"

    path.write_text("{bad", encoding="utf-8")
    with pytest.raises(ConfigError, match="用户配置无法读取"):
        user_prefs.role_model_prefs()


def test_default_location_follows_checkpoint(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("GENI_STUDIO_USER_CONFIG_PATH")
    monkeypatch.setenv("GENI_STUDIO_CHECKPOINT", "sqlite")
    monkeypatch.setenv("GENI_STUDIO_CHECKPOINT_PATH", str(tmp_path / "preview" / "checkpoints.sqlite"))
    assert user_prefs.user_config_file() == tmp_path / "preview" / "user_config.json"


def test_ui_prefs_keep_theme_next_to_model_prefs(tmp_path: Path) -> None:
    assert user_prefs.ui_prefs() == {}
    user_prefs.set_role_model_pref("developer", "cursor", "gpt-5.5", {"effort": "low"})
    assert user_prefs.set_ui_pref("theme", "dark") == {"theme": "dark"}
    saved = json.loads((tmp_path / "user_config.json").read_text(encoding="utf-8"))
    assert saved["ui"] == {"theme": "dark"}
    assert saved["role_model_prefs"]["developer"] == {"cursor:gpt-5.5": {"effort": "low"}}
    assert user_prefs.set_ui_pref("theme", "") == {}, "空值回到系统设置"
    with pytest.raises(ValueError, match="界面偏好只能是 theme"):
        user_prefs.set_ui_pref("sidebar_width", "300px")
    with pytest.raises(ValueError, match="须为 light、dark"):
        user_prefs.set_ui_pref("theme", "blue")

    client = TestClient(app)
    assert client.put("/api/config/user/ui", json={"name": "theme", "value": "light"}).json() == {"ui": {"theme": "light"}}
    assert client.get("/api/config/user/ui").json() == {"ui": {"theme": "light"}}
    assert client.put("/api/config/user/ui", json={"name": "theme", "value": "blue"}).status_code == 400


def test_api_round_trip() -> None:
    client = TestClient(app)
    assert client.get(URL).json() == {"role_model_prefs": {}}
    body = {"role": "developer", "backend": "cursor", "model": "claude-opus-5-5", "effort": "high",
            "params": {"context": "300k"}}
    response = client.put(URL, json=body)
    assert response.status_code == 200
    expected = {"developer": {"cursor:claude-opus-5-5": {"effort": "high", "params": {"context": "300k"}}}}
    assert response.json()["role_model_prefs"] == expected
    assert client.get(URL).json()["role_model_prefs"] == expected
    bad = client.put(URL, json={**body, "params": {"context": "3 m"}})
    assert bad.status_code == 400 and "取值无效" in bad.json()["detail"]
