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
