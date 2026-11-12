"""Run 推理配置从 API 到检查点和角色调用的传递。"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

from geni_studio.backends.reasoning import reasoning_for_role
from geni_studio.hitl.service import GraphRunService
from geni_studio.web.app import app
from geni_studio.workflows.default import compile_graph


def test_draft_effort_roundtrip_and_copy(tmp_path, monkeypatch):
    monkeypatch.setattr("geni_studio.hitl.drafts.drafts_dir", lambda: tmp_path)
    client = TestClient(app)
    body = {"project_id": "effort-draft", "run_name": "推理草稿",
            "role_models": {"developer": "gpt-test"},
            "role_reasoning_efforts": {"developer": "HIGH", "tester": "default", "qa": ""}}
    response = client.put("/api/runs/drafts", json=body)
    assert response.status_code == 200
    draft = response.json()
    expected = {"developer": "high", "tester": "default"}
    assert draft["role_reasoning_efforts"] == expected
    assert client.get(f"/api/runs/drafts/{draft['draft_id']}").json()["role_reasoning_efforts"] == expected
    service = GraphRunService(compile_graph(checkpointer=MemorySaver()))
    assert service.copy_run_template(draft["draft_id"])["role_reasoning_efforts"] == expected
    body.update(draft_id=draft["draft_id"], role_reasoning_efforts={"developer": "typo"})
    assert client.put("/api/runs/drafts", json=body).status_code == 400
    assert client.get(f"/api/runs/drafts/{draft['draft_id']}").json()["role_reasoning_efforts"] == expected


def test_run_effort_survives_service_reload_resume_and_copy(monkeypatch):
    from geni_studio.backends import runner

    original = runner.invoke_role
    observed = []

    def invoke(**kwargs):
        observed.append((kwargs["role_name"], reasoning_for_role(kwargs["role_name"], "inherited")))
        return original(**kwargs)

    monkeypatch.setattr(runner, "invoke_role", invoke)
    graph = compile_graph(checkpointer=MemorySaver())
    service = GraphRunService(graph)
    efforts = {"project_manager": "high", "tester": "default", "architect": "low"}
    status = service.start(human_request="推理设置回归", role_reasoning_efforts=efforts)
    tid = status.thread_id
    assert status.values["role_reasoning_efforts"] == efforts
    assert ("project_manager", "high") in observed and ("tester", "default") in observed
    assert reasoning_for_role("project_manager", "outside") == "outside"
    restored = GraphRunService(graph)
    assert restored.copy_run_template(tid)["role_reasoning_efforts"] == efforts
    restored.submit_hitl(tid, gate_decision="approved")
    assert ("architect", "low") in observed
    assert restored.status(tid).values["role_reasoning_efforts"] == efforts
    restored.set_role_models(tid, {"developer": "gpt-test"})
    assert restored.status(tid).values["role_reasoning_efforts"] == efforts
    with pytest.raises(ValueError):
        restored.set_role_models(tid, {"developer": "wrong"}, {"developer": "typo"})
    assert restored.status(tid).values["role_models"] == {"developer": "gpt-test"}
    restored.set_role_models(tid, {}, {})
    assert restored.status(tid).values["role_reasoning_efforts"] == {}


def test_start_api_and_legacy_role_update(monkeypatch):
    service = GraphRunService(compile_graph(checkpointer=MemorySaver()))
    monkeypatch.setattr("geni_studio.web.app._service", service)
    client = TestClient(app)
    response = client.post("/api/runs", json={
        "human_request": "推理 API", "role_reasoning_efforts": {"developer": "high"},
    })
    assert response.status_code == 200, response.text
    tid = response.json()["thread_id"]
    url = f"/api/runs/{tid}/role-models"
    updated = client.put(url, json={"role_models": {"developer": "gpt-test"}})
    assert updated.json()["values"]["role_reasoning_efforts"] == {"developer": "high"}
    invalid = client.post("/api/runs", json={
        "human_request": "invalid", "role_reasoning_efforts": {"developer": "typo"},
    })
    assert invalid.status_code == 400


def test_fast_modes_roundtrip_through_draft_start_update_and_copy(tmp_path, monkeypatch):
    from geni_studio.backends import runner
    from geni_studio.backends.reasoning import fast_for_role

    monkeypatch.setattr("geni_studio.hitl.drafts.drafts_dir", lambda: tmp_path)
    service = GraphRunService(compile_graph(checkpointer=MemorySaver()))
    monkeypatch.setattr("geni_studio.web.app._service", service)
    client = TestClient(app)
    draft = client.put("/api/runs/drafts", json={
        "project_id": "fast-draft", "run_name": "Fast 草稿",
        "role_fast_modes": {"developer": "ON", "tester": "default"},
    }).json()
    assert draft["role_fast_modes"] == {"developer": "on"}
    assert service.copy_run_template(draft["draft_id"])["role_fast_modes"] == {"developer": "on"}
    bad = client.put("/api/runs/drafts", json={"project_id": "fast-draft", "role_fast_modes": {"developer": "turbo"}})
    assert bad.status_code == 400

    original = runner.invoke_role
    observed = []

    def invoke(**kwargs):
        observed.append((kwargs["role_name"], fast_for_role(kwargs["role_name"])))
        return original(**kwargs)

    monkeypatch.setattr(runner, "invoke_role", invoke)
    response = client.post("/api/runs", json={
        "human_request": "Fast 回归", "role_fast_modes": {"project_manager": "off"},
    })
    assert response.status_code == 200, response.text
    tid = response.json()["thread_id"]
    service.advance_until_blocked(tid)
    assert ("project_manager", "off") in observed
    url = f"/api/runs/{tid}/role-models"
    updated = client.put(url, json={"role_models": {}, "role_fast_modes": {"architect": "on"}})
    assert updated.json()["values"]["role_fast_modes"] == {"architect": "on"}
    kept = client.put(url, json={"role_models": {"developer": "gpt-test"}})
    assert kept.json()["values"]["role_fast_modes"] == {"architect": "on"}
    assert service.copy_run_template(tid)["role_fast_modes"] == {"architect": "on"}


def test_model_params_roundtrip_through_draft_start_update_and_copy(tmp_path, monkeypatch):
    from geni_studio.backends import runner
    from geni_studio.backends.reasoning import model_params_for_role

    monkeypatch.setattr("geni_studio.hitl.drafts.drafts_dir", lambda: tmp_path)
    service = GraphRunService(compile_graph(checkpointer=MemorySaver()))
    monkeypatch.setattr("geni_studio.web.app._service", service)
    client = TestClient(app)
    draft = client.put("/api/runs/drafts", json={
        "project_id": "ctx-draft", "run_name": "上下文草稿",
        "role_model_params": {"developer": {"context": "1m"}, "tester": {"context": ""}},
    }).json()
    assert draft["role_model_params"] == {"developer": {"context": "1m"}}
    assert service.copy_run_template(draft["draft_id"])["role_model_params"] == {"developer": {"context": "1m"}}
    bad = client.put("/api/runs/drafts", json={
        "project_id": "ctx-draft", "role_model_params": {"developer": {"thinking": "true"}},
    })
    assert bad.status_code == 400

    original = runner.invoke_role
    observed = []

    def invoke(**kwargs):
        observed.append((kwargs["role_name"], model_params_for_role(kwargs["role_name"])))
        return original(**kwargs)

    monkeypatch.setattr(runner, "invoke_role", invoke)
    response = client.post("/api/runs", json={
        "human_request": "上下文回归", "role_model_params": {"project_manager": {"context": "272k"}},
    })
    assert response.status_code == 200, response.text
    tid = response.json()["thread_id"]
    service.advance_until_blocked(tid)
    assert ("project_manager", {"context": "272k"}) in observed
    url = f"/api/runs/{tid}/role-models"
    updated = client.put(url, json={"role_models": {}, "role_model_params": {"architect": {"context": "1m"}}})
    assert updated.json()["values"]["role_model_params"] == {"architect": {"context": "1m"}}
    kept = client.put(url, json={"role_models": {"developer": "gpt-test"}})
    assert kept.json()["values"]["role_model_params"] == {"architect": {"context": "1m"}}
    assert service.copy_run_template(tid)["role_model_params"] == {"architect": {"context": "1m"}}


def test_codex_fast_tier_reads_service_tiers_and_legacy_speed_tiers():
    from geni_studio.backends.codex_backend import _fast_tier

    tier = SimpleNamespace(id="priority", name="Fast", description="2x speed")
    assert _fast_tier(SimpleNamespace(service_tiers=[tier])) == "priority"
    assert _fast_tier(SimpleNamespace(service_tiers=[], additional_speed_tiers=["fast"])) == "fast"
    assert _fast_tier(SimpleNamespace(service_tiers=None)) == ""


def test_role_defaults_resolve_project_and_frozen_config(monkeypatch):
    service = GraphRunService(compile_graph(checkpointer=MemorySaver()))
    config = {"backends": {
        "developer": {"model": "project-model", "reasoning_effort": "high"},
        "tester": {"backend": "cursor", "reasoning_effort": "extra-high"},
        "finance": {"backend": "cursor"},
        "qa": {"reasoning_effort": "default"},
    }, "secret": "never expose"}
    monkeypatch.setenv("GENI_STUDIO_BACKEND", "codex")
    monkeypatch.setenv("GENI_STUDIO_CODEX_MODEL", "factory-model")
    monkeypatch.setenv("GENI_STUDIO_CODEX_REASONING_EFFORT", "low")
    monkeypatch.setattr("geni_studio.config.context.build_run_context", lambda **kw: SimpleNamespace(merged=config))
    roles = service.role_defaults(project_id="example")["roles"]
    assert roles["developer"] == {"backend": "codex", "model": "project-model", "reasoning_effort": "high"}
    assert roles["tester"] == {"backend": "cursor", "model": "", "reasoning_effort": "extra-high"}
    assert roles["finance"]["reasoning_effort"] == "", "Cursor 角色不继承 Codex 的工厂推理强度"
    assert roles["qa"]["reasoning_effort"] == ""
    assert roles["architect"]["model"] == "factory-model"
    assert "secret" not in str(roles)
    frozen = {"_backend": "codex", "_models": {"codex": "old-model"}, "_codex_reasoning_effort": "medium"}
    monkeypatch.setattr(service, "status", lambda tid: SimpleNamespace(values={"config_snapshot_effective": frozen}))
    assert service.role_defaults(thread_id="old")["roles"]["developer"] == {
        "backend": "codex", "model": "old-model", "reasoning_effort": "medium",
    }
