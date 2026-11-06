"""Run 命名：默认为项目标识加递增序号，也可自定义。"""

import pytest
from fastapi.testclient import TestClient

from auto_studio.hitl.run_name import (
    assign_run_name,
    clean_run_name,
    next_run_name,
    taken_names_for_project,
)
from auto_studio.hitl.service import GraphRunService, HitlError, latest_run_records
from auto_studio.web.app import app
from auto_studio.workflows.default import graph


def test_next_number_follows_the_highest_suffix():
    taken = {"_example-1", "_example-3", "其他", "other-9"}
    assert next_run_name("_example", taken) == "_example-4"
    assert next_run_name("other", taken) == "other-10"
    assert next_run_name("fresh", set()) == "fresh-1"


def test_assign_keeps_custom_name_and_bumps_a_taken_default():
    taken = {"_example-1"}
    assert assign_run_name("_example", "手工命名", taken) == "手工命名"
    assert assign_run_name("_example", "", taken) == "_example-2"
    assert assign_run_name("_example", "_example-1", taken) == "_example-2"
    assert assign_run_name("", "", set()) == ""


def test_clean_run_name_rejects_slash_and_overlong():
    assert clean_run_name("  交付  一  ") == "交付 一"
    with pytest.raises(HitlError):
        clean_run_name("a/b")
    with pytest.raises(HitlError):
        clean_run_name("名" * 65)


@pytest.fixture
def svc() -> GraphRunService:
    return GraphRunService(graph)


def test_start_stores_custom_name_then_increments(svc: GraphRunService) -> None:
    before = next_run_name(
        "_example",
        taken_names_for_project(latest_run_records(graph), "_example"),
    )
    custom = svc.start(
        human_request="自定义",
        project_id="_example",
        run_name="联调命名",
    )
    assert custom.values.get("run_name") == "联调命名"
    assert custom.values.get("project_id") == "_example"
    first = svc.start(human_request="默认一", project_id="_example")
    assert first.values.get("run_name") == before
    second = svc.start(human_request="默认二", project_id="_example", run_name=before)
    assert second.values.get("run_name") == next_run_name("_example", {before})
    names = {
        str(values.get("run_name") or "")
        for _tid, values in latest_run_records(graph)
        if values.get("project_id") == "_example"
    }
    assert {"联调命名", before, second.values.get("run_name")} <= names


def test_api_next_name_and_start_round_trip() -> None:
    client = TestClient(app)
    missing = client.get("/api/runs/next-name")
    assert missing.status_code == 400
    suggested = client.get("/api/runs/next-name", params={"project_id": "_example"})
    assert suggested.status_code == 200
    name = suggested.json()["run_name"]
    assert name.startswith("_example-")
    started = client.post(
        "/api/runs",
        json={
            "human_request": "接口命名",
            "project_id": "_example",
            "run_name": name,
        },
    )
    assert started.status_code == 200
    assert started.json()["values"]["run_name"] == name
    nxt = client.get("/api/runs/next-name", params={"project_id": "_example"})
    assert nxt.json()["run_name"] != name
    bad = client.post(
        "/api/runs",
        json={"human_request": "坏名字", "project_id": "_example", "run_name": "a/b"},
    )
    assert bad.status_code == 400


def test_run_page_has_name_field() -> None:
    client = TestClient(app)
    text = client.get("/").text
    assert 'id="runName"' in text
    assert "Run 命名" in text
