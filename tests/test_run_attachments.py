"""提示词附件先暂存，启动时拷进工作区，并写进角色提示。"""

from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from geni_studio.hitl.attachments import prompt_section, stage_attachments, store_upload
from geni_studio.hitl.service import HitlError
from geni_studio.web.app import app


def test_upload_is_staged_and_mentioned(tmp_path, monkeypatch) -> None:
    uploads = tmp_path / "uploads"
    drafts = tmp_path / "drafts"
    uploads.mkdir()
    drafts.mkdir()
    monkeypatch.setattr("geni_studio.hitl.attachments.uploads_dir", lambda: uploads)
    monkeypatch.setattr("geni_studio.hitl.drafts.drafts_dir", lambda: drafts)
    client = TestClient(app)
    empty = client.post("/api/runs/attachments", headers={"X-Filename": "note.txt"}, content=b"")
    assert empty.status_code == 400

    saved = client.post(
        "/api/runs/attachments",
        headers={"X-Filename": quote("说明.txt")},
        content="先看这份".encode(),
    )
    assert saved.status_code == 200
    body = saved.json()
    assert body["name"] == "说明.txt"
    assert body["size"] == len("先看这份".encode())

    placed = stage_attachments([body["id"]], tmp_path / "work" / "attachments")
    assert placed == ["attachments/说明.txt"]
    assert (tmp_path / "work" / "attachments" / "说明.txt").read_text(encoding="utf-8") == "先看这份"
    assert "说明.txt" in prompt_section(placed)

    draft = client.put(
        "/api/runs/drafts",
        json={
            "project_id": "draft-sample",
            "run_name": "带附件",
            "human_request": "按附件实现",
            "attachments": [{"id": body["id"], "name": body["name"], "size": body["size"]}],
        },
    )
    assert draft.status_code == 200
    assert draft.json()["attachments"][0]["id"] == body["id"]


def test_store_rejects_a_blank_name(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("geni_studio.hitl.attachments.uploads_dir", lambda: tmp_path)
    with pytest.raises(HitlError, match="名称"):
        store_upload("   ", b"x")
