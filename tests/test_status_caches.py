"""页面首屏要读的慢接口在短时内复用上一次结果。"""

from __future__ import annotations

import time

from geni_studio.backends import models
from geni_studio.hitl import lark_cli_client
from geni_studio.hitl.lark_cli_client import LarkCliAuthSummary


def test_auth_summary_reuses_recent_result(monkeypatch):
    calls = []

    def query():
        calls.append(1)
        return LarkCliAuthSummary(True, True, True, "ok")

    monkeypatch.setattr(lark_cli_client, "_query_auth_summary", query)
    monkeypatch.setattr(lark_cli_client, "_auth_cache", {"at": 0.0, "value": None})
    assert lark_cli_client.auth_summary().bot_ready
    lark_cli_client.auth_summary()
    assert len(calls) == 1
    lark_cli_client.auth_summary(fresh=True)
    assert len(calls) == 2


def test_cursor_models_served_from_catalog(monkeypatch):
    monkeypatch.setenv("CURSOR_API_KEY", "key-a")
    rows = [{"id": "m1", "label": "M1"}]
    monkeypatch.setattr(models, "_cursor_catalog", {"at": time.monotonic(), "key": "key-a", "rows": rows})

    def fail():
        raise AssertionError("目录未过期时不应重新拉取")

    monkeypatch.setattr(models, "_list_cursor_models", fail)
    assert models.list_backend_models(backend="cursor") == {"models": rows, "source": "cursor", "detail": ""}

    monkeypatch.setenv("CURSOR_API_KEY", "key-b")
    monkeypatch.setattr(models, "_list_cursor_models", lambda: {"models": [], "source": "cursor", "detail": "x"})
    assert models.list_backend_models(backend="cursor")["detail"] == "x"
