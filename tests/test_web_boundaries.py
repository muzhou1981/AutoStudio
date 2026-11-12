"""错误类型决定状态码；状态展示与页面脚本各自独立。"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from geni_studio.config.context import ConfigError, ConfigNotFound
from geni_studio.hitl import presenter
from geni_studio.hitl.service import (
    HitlError,
    NotAwaiting,
    RunBusy,
    RunConflict,
    RunNotFound,
    RunStatus,
)
from geni_studio.web.app import app
from geni_studio.web.errors import status_for

WEB = Path(__file__).resolve().parents[1] / "src" / "geni_studio" / "web"


def test_status_follows_exception_type() -> None:
    assert status_for(RunNotFound("x")) == 404
    assert status_for(ConfigNotFound("x")) == 404
    assert status_for(RunConflict("x")) == 409
    assert status_for(NotAwaiting("x")) == 409
    assert status_for(RunBusy("x")) == 409
    assert status_for(HitlError("未知 thread_id")) == 400
    assert status_for(ConfigError("未知 project_id")) == 400
    assert status_for(HitlError("x"), 409) == 409


def test_routes_do_not_match_error_text() -> None:
    pattern = re.compile(r"in str\((e|exc)\)|str\((e|exc)\)\.startswith|message\.startswith")
    offenders = [
        f"{path.name}:{n}"
        for path in WEB.glob("*.py")
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line)
    ]
    assert offenders == []


def test_unknown_run_and_draft_map_to_404(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("geni_studio.hitl.drafts.drafts_dir", lambda: tmp_path)
    client = TestClient(app)
    assert client.post("/api/runs/no-such-thread/pause").status_code == 404
    assert client.post("/api/runs/drafts/draft-missing/delete", json={"confirm_name": "x"}).status_code == 404


def test_draft_name_mismatch_maps_to_409(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("geni_studio.hitl.drafts.drafts_dir", lambda: tmp_path)
    client = TestClient(app)
    saved = client.put(
        "/api/runs/drafts",
        json={"project_id": "draft-sample", "run_name": "草稿样本", "human_request": "x"},
    )
    draft_id = saved.json()["draft_id"]
    wrong = client.post(f"/api/runs/drafts/{draft_id}/delete", json={"confirm_name": "别的名字"})
    assert wrong.status_code == 409


def test_presenter_payload_shape() -> None:
    st = RunStatus(
        thread_id="t",
        phase="running",
        next_nodes=("project_manager_draft",),
        awaiting_human=None,
        values={"human_request": "x", "extra_artifacts": {"report": "r"}},
    )
    body = presenter.status_payload(st, st.values)
    assert body["values"]["report"] == "r"
    assert "extra_artifacts" not in body["values"]
    assert {"rail", "reading", "choices", "choice_groups", "limits"} <= set(body)


def test_hitl_page_loads_external_script() -> None:
    html = (WEB / "static" / "hitl.html").read_text(encoding="utf-8")
    inline = re.findall(r"<script>(.*?)</script>", html, re.DOTALL)
    assert all(len(block.splitlines()) < 40 for block in inline)
    assert '<script src="/static/hitl.js' in html
    client = TestClient(app)
    assert client.get("/static/hitl.js").status_code == 200


def _node_that_parses_hitl() -> str | None:
    candidates = [Path(d) / "node" for d in os.environ.get("PATH", "").split(os.pathsep)]
    candidates += sorted((Path.home() / ".nvm/versions/node").glob("*/bin/node"), reverse=True)
    for node in candidates:
        if not node.is_file():
            continue
        version = subprocess.run(
            [str(node), "--version"],
            check=False,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if version.startswith("v") and int(version[1:].split(".")[0]) >= 18:
            return str(node)
    return None


def test_hitl_script_parses() -> None:
    node = _node_that_parses_hitl()
    if node is None:
        pytest.skip("需要 Node.js 18 或更新版本")
    subprocess.run([node, "--check", str(WEB / "static" / "hitl.js")], check=True)
