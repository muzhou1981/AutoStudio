"""安全边界：工作区推送防护、Web 访问令牌、审批人身份与名单、飞书回调默认校验。"""

from __future__ import annotations

import json
import os
import subprocess

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver

from geni_studio.hitl.service import GraphRunService, HitlError
from geni_studio.workflows.default import compile_graph
from geni_studio.workspace import push_guard

_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}


def _git(path, *args, check=True):
    return subprocess.run(["git", "-C", os.fspath(path), *args], capture_output=True, text=True, check=check, env=_ENV)


def _repo_with_remote(tmp_path):
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", os.fspath(remote)], check=True)
    repo = tmp_path / "target"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "README.md").write_text("x\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-qm", "init")
    _git(repo, "remote", "add", "origin", os.fspath(remote))
    return repo


def test_run_worktree_cannot_push(tmp_path, monkeypatch):
    repo = _repo_with_remote(tmp_path)
    monkeypatch.setenv("GENI_STUDIO_WORKSPACE", "1")
    monkeypatch.setenv("GENI_STUDIO_TARGET_ROOT", str(repo))
    st = GraphRunService(compile_graph(checkpointer=MemorySaver())).start(
        human_request="推送防护", scenario_key="npu_operator"
    )
    worktree = st.values["workspace_path"]
    assert _git(worktree, "push", "origin", "HEAD", check=False).returncode != 0
    assert _git(worktree, "push", "--no-verify", "origin", "HEAD", check=False).returncode != 0
    assert _git(repo, "push", "-q", "origin", "HEAD", check=False).returncode == 0


def test_current_branch_guard_is_released_by_the_last_holder(tmp_path):
    repo = _repo_with_remote(tmp_path)
    push_guard.install(repo, holder="run-a")
    push_guard.install(repo, holder="run-b")
    assert _git(repo, "push", "--no-verify", "origin", "HEAD", check=False).returncode != 0
    assert push_guard.release(repo, "run-a") is False
    assert push_guard.is_guarded(repo)
    assert push_guard.release(repo, "run-b") is True
    assert not push_guard.is_guarded(repo)
    assert _git(repo, "push", "-q", "origin", "HEAD", check=False).returncode == 0


def test_web_token_is_required_when_set(monkeypatch):
    from geni_studio.web.app import app

    monkeypatch.setenv("GENI_STUDIO_WEB_TOKEN", "secret-web")
    client = TestClient(app)
    assert client.get("/api/runs").status_code == 401
    assert client.get("/api/runs", headers={"X-Geni-Studio-Token": "wrong"}).status_code == 401
    assert client.get("/api/runs", headers={"X-Geni-Studio-Token": "secret-web"}).status_code == 200
    assert client.get("/api/runs", headers={"Authorization": "Bearer secret-web"}).status_code == 200
    assert client.get("/").status_code == 401
    login = client.get("/?token=secret-web", follow_redirects=False)
    assert login.status_code == 303
    assert "geni_studio_token" in login.headers["set-cookie"]
    client.cookies.set("geni_studio_token", "secret-web")
    assert client.get("/api/runs").status_code == 200


def test_listening_beyond_loopback_needs_a_token(monkeypatch):
    from geni_studio.web.auth import check_listen_address

    check_listen_address("127.0.0.1")
    with pytest.raises(SystemExit):
        check_listen_address("0.0.0.0")
    monkeypatch.setenv("GENI_STUDIO_WEB_TOKEN", "secret-web")
    check_listen_address("0.0.0.0")


def test_web_audit_records_the_operator_and_ignores_claimed_channel(monkeypatch):
    from geni_studio.web.app import app, run_service

    monkeypatch.setenv("GENI_STUDIO_WEB_OPERATOR", "alice")
    st = run_service().start(human_request="审批人", scenario_key="npu_operator")
    sent = TestClient(app).post(
        f"/api/runs/{st.thread_id}/hitl",
        json={"gate_decision": "approved", "channel": "feishu"},
    )
    assert sent.status_code == 200
    audit = run_service().status(st.thread_id).values["hitl_audit_log"]
    assert "channel=web actor=alice" in audit
    assert "channel=feishu" not in audit


def _card(thread_id: str, open_id: str) -> dict:
    return {
        "header": {"event_type": "card.action.trigger"},
        "event": {
            "operator": {"open_id": open_id},
            "action": {"value": {"thread_id": thread_id, "hitl_action": "gate", "gate_decision": "approved"}},
        },
    }


def test_feishu_approver_allow_list(monkeypatch):
    from geni_studio.web.app import app, run_service

    monkeypatch.setattr("geni_studio.hitl.feishu_config.feishu_approvers", lambda _pid, **_k: ["ou_ok"])
    st = run_service().start(human_request="审批名单", scenario_key="npu_operator")
    client = TestClient(app)
    denied = client.post("/api/webhooks/feishu", json=_card(st.thread_id, "ou_other"))
    assert denied.status_code == 409
    assert "审批人名单" in denied.json()["detail"]
    assert run_service().status(st.thread_id).awaiting_human.gate_id == "gate_requirement_confirm"
    allowed = client.post("/api/webhooks/feishu", json=_card(st.thread_id, "ou_ok"))
    assert allowed.status_code == 200
    assert "channel=feishu actor=ou_ok" in run_service().status(st.thread_id).values["hitl_audit_log"]

    with pytest.raises(HitlError, match="审批人名单"):
        run_service().submit_hitl(st.thread_id, gate_decision="approved", channel="feishu", actor="")


def test_feishu_approvers_come_from_project_config(tmp_path):
    from geni_studio.hitl.feishu_config import feishu_approvers

    folder = tmp_path / "projects" / "secure"
    folder.mkdir(parents=True)
    (folder / "project.yaml").write_text(
        "project_id: secure\nhitl:\n  feishu:\n    approvers: [ou_a, ou_b]\n", encoding="utf-8"
    )
    assert feishu_approvers("secure", root=tmp_path) == ["ou_a", "ou_b"]
    assert feishu_approvers("", root=tmp_path) == []


def test_feishu_webhook_rejects_without_a_configured_token(monkeypatch):
    from geni_studio.web.app import app

    monkeypatch.delenv("GENI_STUDIO_FEISHU_WEBHOOK_INSECURE", raising=False)
    client = TestClient(app)
    challenge = client.post("/api/webhooks/feishu", json={"challenge": "abc", "type": "url_verification"})
    assert challenge.json() == {"challenge": "abc"}
    event = {"header": {"event_type": "im.message.receive_v1"}, "event": {}}
    assert client.post("/api/webhooks/feishu", json=event).status_code == 401
    assert client.post("/api/webhooks/feishu/card-action", json={"thread_id": "x", "gate_decision": "approved"}).status_code == 401


def test_builtin_bridge_generates_a_webhook_token(monkeypatch):
    from geni_studio.hitl import feishu_bridge

    monkeypatch.delenv("GENI_STUDIO_FEISHU_WEBHOOK_TOKEN", raising=False)
    monkeypatch.setenv("GENI_STUDIO_FEISHU_BRIDGE", "1")
    monkeypatch.setattr(feishu_bridge, "_bridge_started", False)
    monkeypatch.setattr("geni_studio.hitl.lark_cli_client.lark_cli_path", lambda: "/usr/bin/false")
    started: list[str] = []

    class _Thread:
        def __init__(self, *, name: str, **_kwargs):
            started.append(name)

        def start(self):
            pass

    monkeypatch.setattr(feishu_bridge.threading, "Thread", _Thread)
    feishu_bridge.start_background()
    assert len(os.environ["GENI_STUDIO_FEISHU_WEBHOOK_TOKEN"]) >= 32
    assert started


def test_im_reply_records_the_sender(monkeypatch):
    from geni_studio.web.app import app, run_service

    st = run_service().start(human_request="IM 审批人", scenario_key="npu_operator")
    body = {
        "header": {"event_type": "im.message.receive_v1"},
        "event": {
            "message": {
                "message_type": "text",
                "content": json.dumps({"text": f"RUN:{st.thread_id} 批准"}, ensure_ascii=False),
                "chat_id": "oc_sec",
            },
            "sender": {"sender_id": {"open_id": "ou_sender"}},
        },
    }
    replied = TestClient(app).post("/api/webhooks/feishu", json=body)
    assert replied.status_code == 200
    assert "actor=ou_sender" in run_service().status(st.thread_id).values["hitl_audit_log"]
