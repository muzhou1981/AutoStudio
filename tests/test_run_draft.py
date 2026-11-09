"""新建 Run 可以先保存草稿，不进入图。"""

from fastapi.testclient import TestClient

from geni_studio.web.app import app


def test_save_lists_and_deletes_a_draft(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("geni_studio.hitl.drafts.drafts_dir", lambda: tmp_path)
    client = TestClient(app)
    missing = client.put("/api/runs/drafts", json={"project_id": "", "run_name": "空项目"})
    assert missing.status_code == 400

    saved = client.put(
        "/api/runs/drafts",
        json={
            "project_id": "draft-sample",
            "run_name": "草稿样本",
            "human_request": "先记下来",
            "node_tools": {"developer": {"skills": ["review"], "mcp": []}},
            "role_models": {"developer": "composer-2", "qa": ""},
        },
    )
    assert saved.status_code == 200
    body = saved.json()
    assert body["run_name"] == "草稿样本"
    assert body["phase"] == "saved"
    assert body["node_tools"]["developer"]["skills"] == ["review"]
    assert body["role_models"] == {"developer": "composer-2"}

    updated = client.put(
        "/api/runs/drafts",
        json={
            "draft_id": body["draft_id"],
            "project_id": "draft-sample",
            "run_name": "草稿样本",
            "human_request": "改过的目标",
        },
    )
    assert updated.status_code == 200
    assert updated.json()["draft_id"] == body["draft_id"]
    assert updated.json()["human_request"] == "改过的目标"

    listed = client.get("/api/runs").json()["runs"]
    assert any(row.get("draft_id") == body["draft_id"] and row["kind"] == "draft" for row in listed)
    assert client.get(f"/api/runs/drafts/{body['draft_id']}").json()["human_request"] == "改过的目标"

    wrong = client.post(f"/api/runs/drafts/{body['draft_id']}/delete", json={"confirm_name": "不对"})
    assert wrong.status_code == 409
    deleted = client.post(
        f"/api/runs/drafts/{body['draft_id']}/delete",
        json={"confirm_name": "草稿样本"},
    )
    assert deleted.status_code == 200
    assert client.get(f"/api/runs/drafts/{body['draft_id']}").status_code == 404

    page = client.get("/").text
    assert 'id="btnSaveRun"' in page
    assert 'class="run-composer"' in page
    assert page.index('id="region-rail"') < page.index('id="region-prompt"')
