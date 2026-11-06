"""场景材料预检、财务节点开关、状态推送。"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from auto_studio.config.context import ConfigError
from auto_studio.config.precheck import precheck_scenario_materials
from auto_studio.hitl.service import GraphRunService
from auto_studio.web.app import app
from auto_studio.workflows.default import graph


@pytest.fixture
def svc() -> GraphRunService:
    return GraphRunService(graph)


def test_npu_materials_are_complete() -> None:
    precheck_scenario_materials("npu_operator")


def test_missing_domain_material_blocks_start(tmp_path) -> None:
    scenario = tmp_path / "scenarios" / "bare"
    scenario.mkdir(parents=True)
    (scenario / "scenario.yaml").write_text(
        "scenario_key: bare\nmaterials:\n  - domain/isa.md\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="领域资料缺失"):
        precheck_scenario_materials("bare", root=tmp_path)


def test_finance_nodes_run_before_the_architecture_gate(
    svc: GraphRunService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("auto_studio.workflows.default._finance_enabled", lambda state: True)
    st = svc.start(human_request="财务", scenario_key="npu_operator")
    assert st.awaiting_human is not None
    assert st.awaiting_human.gate_id == "gate_requirement_confirm"
    st = svc.submit_hitl(st.thread_id, gate_decision="approved", human_reply="过")
    assert st.awaiting_human is not None
    assert st.awaiting_human.gate_id == "gate_architecture_review"
    assert st.values.get("budget_phase") == "final"
    assert "预算" in str(st.values.get("budget_plan") or "")


def test_finance_stays_off_the_default_path(svc: GraphRunService) -> None:
    st = svc.start(human_request="无财务", scenario_key="npu_operator")
    st = svc.submit_hitl(st.thread_id, gate_decision="approved", human_reply="过")
    assert st.awaiting_human is not None
    assert st.awaiting_human.gate_id == "gate_architecture_review"
    assert not st.values.get("budget_plan")
    states = {cell["id"]: cell["state"] for cell in svc.status_dict(st.thread_id)["rail"]["cells"]}
    assert "finance_budget_rough" not in states
    assert "finance_budget_final" not in states
    assert "finance_cost_snapshot" not in states


def test_status_events_push_the_waiting_round() -> None:
    client = TestClient(app)
    started = client.post(
        "/api/runs",
        json={"human_request": "推送", "scenario_key": "npu_operator"},
    )
    assert started.status_code == 200
    thread_id = started.json()["thread_id"]
    with client.stream("GET", f"/api/runs/{thread_id}/events", params={"once": 1}) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        payload = ""
        for line in response.iter_lines():
            if line.startswith("data:"):
                payload = line.split(":", 1)[1].strip()
                break
    data = json.loads(payload)
    assert data["thread_id"] == thread_id
    assert data["phase"] == "awaiting_human"
    text = client.get("/").text
    assert "/events" in text
    assert "每 2 秒" not in text
