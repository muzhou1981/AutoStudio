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
    assert "fast" not in opus
    assert cursor_model_row(_COMPOSER) == {
        "id": "composer-2.5", "label": "Composer 2.5", "fast": True, "default_fast": "",
    }


def test_fast_default_comes_from_the_default_variant() -> None:
    model = SimpleNamespace(
        id="grok-4.6",
        display_name="Grok 4.6",
        parameters=(SimpleNamespace(id="fast", values=(_value("false"), _value("true"))),),
        variants=(SimpleNamespace(params=(_param("fast", "true"),), is_default=True),),
    )
    assert cursor_model_row(model)["default_fast"] == "on"


def test_model_selection_adds_fast_only_for_models_that_declare_it(monkeypatch) -> None:
    from geni_studio.backends.cursor_backend import _model_selection

    rows = [cursor_model_row(item) for item in (_GROK, _OPUS)]
    monkeypatch.setattr("geni_studio.backends.models._cursor_rows", lambda: rows)
    assert _model_selection("grok-4.7", "", "on").to_json() == {
        "id": "grok-4.7",
        "params": [{"id": "fast", "value": "true"}],
    }
    assert _model_selection("grok-4.7", "high", "off").to_json() == {
        "id": "grok-4.7",
        "params": [{"id": "reasoning_effort", "value": "high"}, {"id": "fast", "value": "false"}],
    }
    with pytest.raises(ValueError, match="不支持 Fast"):
        _model_selection("claude-opus-5-5", "", "on")
    with pytest.raises(ValueError, match="Fast 模式"):
        _model_selection("default", "", "on")


_GPT = SimpleNamespace(
    id="gpt-5.5",
    display_name="GPT-5.5",
    parameters=(
        SimpleNamespace(id="context", values=(_value("272k", "272K"), _value("1m", "1M"))),
        SimpleNamespace(id="reasoning", values=(_value("low"), _value("high"))),
        SimpleNamespace(id="fast", values=(_value("false"), _value("true"))),
    ),
    variants=tuple(
        SimpleNamespace(
            params=(_param("cyber", "false"), _param("context", ctx), _param("reasoning", effort), _param("fast", fast)),
            is_default=(ctx, effort, fast) == ("1m", "low", "false"),
        )
        for ctx in ("272k", "1m")
        for effort in ("low", "high")
        for fast in ("false", "true")
        if not (ctx == "1m" and fast == "true")
    ),
)


def test_model_rows_list_context_values_and_allowed_combinations() -> None:
    row = cursor_model_row(_GPT)
    assert row["params"] == [{
        "id": "context",
        "values": [{"id": "272k", "label": "272K"}, {"id": "1m", "label": "1M"}],
        "default": "1m",
    }]
    assert len(row["variants"]) == 6
    assert {"context": "1m", "reasoning": "high", "fast": "false"} in row["variants"]
    assert all("cyber" not in combo for combo in row["variants"]), "未开放的参数不进入组合"
    full = SimpleNamespace(**{**vars(_GPT), "variants": tuple(
        SimpleNamespace(params=(_param("context", c), _param("reasoning", e), _param("fast", f)), is_default=False)
        for c in ("272k", "1m") for e in ("low", "high") for f in ("false", "true")
    )})
    assert "variants" not in cursor_model_row(full), "全组合都允许时不下发组合表"


def test_model_selection_passes_context_and_rejects_combinations_outside_the_catalog(monkeypatch) -> None:
    from geni_studio.backends.cursor_backend import _model_selection

    rows = [cursor_model_row(item) for item in (_GPT, _OPUS)]
    monkeypatch.setattr("geni_studio.backends.models._cursor_rows", lambda: rows)
    assert _model_selection("gpt-5.5", "high", "", {"context": "272k"}).to_json() == {
        "id": "gpt-5.5",
        "params": [{"id": "reasoning", "value": "high"}, {"id": "context", "value": "272k"}],
    }
    assert _model_selection("gpt-5.5", "", "on").to_json()["params"] == [
        {"id": "fast", "value": "true"}, {"id": "context", "value": "272k"},
    ], "默认上下文 1m 不能与 Fast 同用时，显式补上离默认最近的允许取值"
    assert _model_selection("gpt-5.5", "", "on", {"context": "272k"}).to_json()["params"] == [
        {"id": "fast", "value": "true"}, {"id": "context", "value": "272k"},
    ]
    with pytest.raises(ValueError, match="不支持这组参数"):
        _model_selection("gpt-5.5", "", "on", {"context": "1m"})
    with pytest.raises(ValueError, match="不支持取值 2m"):
        _model_selection("gpt-5.5", "", "", {"context": "2m"})
    with pytest.raises(ValueError, match="没有参数 context"):
        _model_selection("claude-opus-5-5", "", "", {"context": "1m"})
    with pytest.raises(ValueError, match="上下文长度"):
        _model_selection("default", "", "", {"context": "1m"})


def test_model_params_are_cleaned_and_scoped_to_the_run() -> None:
    from geni_studio.backends.reasoning import (
        clean_role_model_params,
        model_params_for_role,
        use_role_model_params,
    )

    assert clean_role_model_params({"developer": {"context": " 1m "}, "qa": {"context": ""}, "pm": {}}) == {
        "developer": {"context": "1m"},
    }
    with pytest.raises(ValueError, match="只能是 context"):
        clean_role_model_params({"developer": {"thinking": "true"}})
    with pytest.raises(ValueError, match="取值无效"):
        clean_role_model_params({"developer": {"context": "1 m;"}})
    assert model_params_for_role("developer") == {}
    with use_role_model_params({"developer": {"context": "272k"}}):
        assert model_params_for_role("developer") == {"context": "272k"}
        assert model_params_for_role("tester") == {}
    assert model_params_for_role("developer") == {}


def test_cursor_backend_keeps_agents_apart_by_context(monkeypatch, tmp_path) -> None:
    from geni_studio.backends import runner
    from geni_studio.backends.cursor_backend import CursorBackend
    from geni_studio.backends.reasoning import use_role_model_params
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
    monkeypatch.setattr("geni_studio.backends.models._cursor_rows", lambda: [cursor_model_row(_GPT)])
    monkeypatch.setattr(runner, "_role_config", lambda role, project_id="": {})
    (tmp_path / ".geni_studio").mkdir()
    token = bind_thread("run-context")
    try:
        for chosen in ({"architect": {"context": "272k"}}, {}):
            with use_worktree(tmp_path), use_role_model_params(chosen):
                CursorBackend().complete(role_name="architect", system_prompt="角色", user_prompt="写设计", model="gpt-5.5")
    finally:
        unbind_thread(token)
    assert created[0].to_json() == {"id": "gpt-5.5", "params": [{"id": "context", "value": "272k"}]}
    assert created[1] == "gpt-5.5", "上下文长度不同的调用不共用 Agent"


def test_fast_modes_are_cleaned_and_scoped_to_the_run() -> None:
    from geni_studio.backends.reasoning import (
        clean_role_fast_modes,
        fast_for_role,
        use_role_fast_modes,
    )

    assert clean_role_fast_modes({"developer": "ON", "tester": "default", "qa": ""}) == {"developer": "on"}
    with pytest.raises(ValueError, match="fast"):
        clean_role_fast_modes({"developer": "turbo"})
    assert fast_for_role("developer") == ""
    with use_role_fast_modes({"developer": "off"}):
        assert fast_for_role("developer") == "off"
        assert fast_for_role("tester") == ""
    assert fast_for_role("developer") == ""


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
    assert created == [expected], "同一角色的不同节点共用一个会话，模型与推理强度一致"
