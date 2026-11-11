"""Cursor 后端的角色推理强度：模型目录、ModelSelection 组装与按角色生效。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from geni_studio.backends.models import cursor_effort_param, cursor_model_row
from geni_studio.backends.reasoning import (
    clean_role_reasoning_efforts,
    use_role_reasoning_efforts,
)

pytest.importorskip("cursor_sdk")


def _value(value: str, name: str = "") -> SimpleNamespace:
    return SimpleNamespace(value=value, display_name=name or value.title())


def _param(pid: str, value: str) -> SimpleNamespace:
    return SimpleNamespace(id=pid, value=value)


_GROK = SimpleNamespace(
    id="grok-4.7",
    display_name="Grok 4.7",
    parameters=(
        SimpleNamespace(id="context", values=(_value("256k"), _value("500k"))),
        SimpleNamespace(id="reasoning_effort", values=(_value("low"), _value("medium"), _value("high"))),
        SimpleNamespace(id="fast", values=(_value("false"), _value("true"))),
    ),
    variants=(
        SimpleNamespace(params=(_param("reasoning_effort", "low"),), is_default=False),
        SimpleNamespace(params=(_param("reasoning_effort", "medium"),), is_default=True),
    ),
)
_OPUS = SimpleNamespace(
    id="claude-opus-5-5",
    display_name="Claude Opus 5.5",
    parameters=(SimpleNamespace(id="effort", values=(_value("low"), _value("max"))),),
    variants=(),
)
_COMPOSER = SimpleNamespace(
    id="composer-2.5",
    display_name="Composer 2.5",
    parameters=(SimpleNamespace(id="fast", values=(_value("false"), _value("true"))),),
    variants=(),
)


def test_model_rows_carry_the_reasoning_parameter_of_each_model() -> None:
    grok = cursor_model_row(_GROK)
    assert grok["reasoning_param"] == "reasoning_effort"
    assert [item["id"] for item in grok["reasoning_efforts"]] == ["low", "medium", "high"]
    assert grok["default_reasoning_effort"] == "medium"
    opus = cursor_model_row(_OPUS)
    assert opus["reasoning_param"] == "effort"
    assert opus["default_reasoning_effort"] == ""
    assert cursor_model_row(_COMPOSER) == {"id": "composer-2.5", "label": "Composer 2.5"}


def test_effort_param_is_checked_against_the_catalog(monkeypatch) -> None:
    rows = [cursor_model_row(item) for item in (_GROK, _OPUS, _COMPOSER)]
    monkeypatch.setattr("geni_studio.backends.models._cursor_rows", lambda: rows)
    assert cursor_effort_param("grok-4.7", "high") == "reasoning_effort"
    assert cursor_effort_param("claude-opus-5-5", "max") == "effort"
    with pytest.raises(ValueError, match="不支持推理强度 max"):
        cursor_effort_param("grok-4.7", "max")
    with pytest.raises(ValueError, match="不支持设置推理强度"):
        cursor_effort_param("composer-2.5", "low")
    monkeypatch.setattr("geni_studio.backends.models._cursor_rows", list)
    with pytest.raises(RuntimeError, match="读不到 Cursor 模型列表"):
        cursor_effort_param("grok-4.7", "low")


def test_model_selection_only_adds_params_when_an_effort_is_set(monkeypatch) -> None:
    from geni_studio.backends.cursor_backend import _model_selection

    rows = [cursor_model_row(_GROK)]
    monkeypatch.setattr("geni_studio.backends.models._cursor_rows", lambda: rows)
    assert _model_selection("grok-4.7", "") == "grok-4.7"
    assert _model_selection("grok-4.7", "high").to_json() == {
        "id": "grok-4.7",
        "params": [{"id": "reasoning_effort", "value": "high"}],
    }
    with pytest.raises(ValueError, match="Auto"):
        _model_selection("default", "high")


def test_effort_for_role_prefers_the_run_override(monkeypatch) -> None:
    from geni_studio.backends import runner

    monkeypatch.setattr(runner, "_role_config", lambda role, project_id="": {"reasoning_effort": "low"})
    assert runner.effort_for_role("developer") == "low"
    with use_role_reasoning_efforts({"developer": "HIGH", "tester": "default"}):
        assert runner.effort_for_role("developer") == "high"
        assert runner.effort_for_role("tester") == ""
        assert runner.effort_for_role("qa") == "low"


def test_role_efforts_accept_cursor_values_and_reject_typos() -> None:
    assert clean_role_reasoning_efforts({"developer": "Extra-High", "qa": ""}) == {"developer": "extra-high"}
    with pytest.raises(ValueError):
        clean_role_reasoning_efforts({"developer": "typo"})


def test_cursor_backend_creates_the_agent_with_the_role_effort(monkeypatch, tmp_path) -> None:
    from geni_studio.backends import runner
    from geni_studio.backends.cursor_backend import CursorBackend
    from geni_studio.hitl.control import bind_thread, unbind_thread
    from geni_studio.workspace.context import use_worktree

    created = []

    class _Agent:
        agent_id = "agent-1"

        def send(self, prompt, options=None):
            return SimpleNamespace(text=lambda: "ok")

    class _Client:
        def create_agent(self, opts, api_key=None):
            created.append(opts.model)
            return _Agent()

    monkeypatch.setenv("CURSOR_API_KEY", "test-key")
    monkeypatch.setattr("cursor_sdk._client._default_client", lambda: _Client())
    monkeypatch.setattr("geni_studio.backends.models._cursor_rows", lambda: [cursor_model_row(_GROK)])
    monkeypatch.setattr(runner, "_role_config", lambda role, project_id="": {})
    (tmp_path / ".geni_studio").mkdir()
    token = bind_thread("run-effort")
    try:
        with use_worktree(tmp_path), use_role_reasoning_efforts({"architect": "high"}):
            CursorBackend().complete(role_name="architect", system_prompt="角色", user_prompt="写设计", model="grok-4.7")
        with use_worktree(tmp_path):
            CursorBackend().complete(role_name="architect", system_prompt="角色", user_prompt="写设计", model="grok-4.7")
    finally:
        unbind_thread(token)
    assert created[0].to_json() == {"id": "grok-4.7", "params": [{"id": "reasoning_effort", "value": "high"}]}
    assert created[1] == "grok-4.7", "不同推理强度不共用 Agent，未设置时只传模型 ID"


def test_same_role_uses_one_model_and_effort_on_every_node(monkeypatch, tmp_path) -> None:
    from geni_studio.backends import runner
    from geni_studio.backends.cursor_backend import CursorBackend
    from geni_studio.hitl.control import bind_thread, unbind_thread
    from geni_studio.workspace.context import use_worktree

    created = []

    class _Agent:
        agent_id = "agent-1"

        def send(self, prompt, options=None):
            return SimpleNamespace(text=lambda: "ok")

    class _Client:
        def create_agent(self, opts, api_key=None):
            created.append(opts.model.to_json())
            return _Agent()

    node = {"id": ""}
    monkeypatch.setenv("CURSOR_API_KEY", "test-key")
    monkeypatch.setattr("cursor_sdk._client._default_client", lambda: _Client())
    backend = CursorBackend()
    monkeypatch.setattr("geni_studio.backends.models._cursor_rows", lambda: [cursor_model_row(_GROK)])
    monkeypatch.setattr("geni_studio.backends.session.current_node_id", lambda: node["id"])
    monkeypatch.setattr(runner, "_role_config", lambda role, project_id="": {})
    monkeypatch.setattr(runner, "backend_for_role", lambda role, project_id="": backend)
    monkeypatch.setattr(runner, "required_capabilities", lambda role: frozenset())
    monkeypatch.setattr(runner, "load_role_system_prompt", lambda role: "角色")
    (tmp_path / ".geni_studio").mkdir()
    token = bind_thread("run-shared-role")
    models = runner.set_role_models({"project_manager": "grok-4.7"})
    try:
        with use_worktree(tmp_path), use_role_reasoning_efforts({"project_manager": "low"}):
            for node_id in ("hear", "write_delivery"):
                node["id"] = node_id
                runner.invoke_role(role_name="project_manager", user_prompt="做事", stub_note=node_id)
    finally:
        runner.reset_role_models(models)
        unbind_thread(token)
    expected = {"id": "grok-4.7", "params": [{"id": "reasoning_effort", "value": "low"}]}
    assert created == [expected, expected], "同一角色的不同节点各建会话，但模型与推理强度相同"
