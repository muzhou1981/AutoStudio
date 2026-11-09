"""删除一轮：名称必须一致，运行中的一轮要先停止。"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from geni_studio.hitl.service import GraphRunService, HitlError
from geni_studio.web.app import app
from geni_studio.workflows.default import graph


@pytest.fixture
def svc() -> GraphRunService:
    return GraphRunService(graph)


def test_delete_requires_the_exact_name_and_then_removes_the_round(svc: GraphRunService) -> None:
    st = svc.start(human_request="待删", scenario_key="npu_operator", run_name="待删样本")
    with pytest.raises(HitlError, match="名称不一致"):
        svc.delete_run(st.thread_id, confirm_name="别的名字")
    assert svc.status(st.thread_id).phase == "awaiting_human"
    svc.delete_run(st.thread_id, confirm_name="待删样本")
    with pytest.raises(HitlError, match="未知"):
        svc.status(st.thread_id)
    assert all(row["thread_id"] != st.thread_id for row in svc.list_runs())


def test_delete_refuses_a_running_round(svc: GraphRunService, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        svc,
        "status",
        lambda thread_id: SimpleNamespace(
            phase="running",
            values={"run_name": "活的"},
            thread_id=thread_id,
        ),
    )
    with pytest.raises(HitlError, match="还在运行"):
        svc.delete_run("running-thread", confirm_name="活的")


def test_api_delete_round_trip() -> None:
    client = TestClient(app)
    started = client.post(
        "/api/runs",
        json={"human_request": "接口删除", "scenario_key": "npu_operator", "run_name": "接口样本"},
    )
    thread_id = started.json()["thread_id"]
    wrong = client.post(
        f"/api/runs/{thread_id}/delete",
        json={"confirm_name": "不对"},
    )
    assert wrong.status_code == 409
    assert client.get(f"/api/runs/{thread_id}").status_code == 200
    deleted = client.post(
        f"/api/runs/{thread_id}/delete",
        json={"confirm_name": "接口样本"},
    )
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    assert client.get(f"/api/runs/{thread_id}").status_code == 404
    page = client.get("/").text
    assert "确认删除" in page
    assert "这一轮记录不能恢复" in page
