"""Codex 会话记录：不依赖 SDK，只检查写入会话文件的事件。"""

import json
from types import SimpleNamespace

from geni_studio.backends.codex_backend import _consume_turn


def _event(method, data):
    return SimpleNamespace(method=method, payload=SimpleNamespace(model_dump=lambda **_: data))


class _Handle:
    id = "turn1"

    def __init__(self, events):
        self._events = events

    def stream(self):
        yield from self._events


def test_turn_records_only_completed_items_and_errors(tmp_path):
    item = {"type": "agentMessage", "id": "m1", "text": "完成", "phase": "final_answer"}
    events = [
        _event("item/started", {"turnId": "turn1", "item": {"type": "agentMessage", "id": "m1"}}),
        *[_event("item/agentMessage/delta", {"turnId": "turn1", "delta": ch}) for ch in "完成"],
        _event("item/reasoning/summaryTextDelta", {"turnId": "turn1", "delta": "想"}),
        _event("item/commandExecution/outputDelta", {"turnId": "turn1", "delta": "out"}),
        _event("item/completed", {"turnId": "turn1", "item": item}),
        _event("error", {"turnId": "turn1", "error": {"message": "重试"}}),
        _event("thread/tokenUsage/updated", {"turnId": "turn1", "tokenUsage": {"total": 1}}),
        _event("turn/completed", {"turn": {"id": "turn1", "status": "completed", "items": [item]}}),
    ]
    path = tmp_path / "001.jsonl"
    text, usage = _consume_turn(_Handle(events), path)
    assert text == "完成"
    assert usage == {"total": 1}
    recorded = [json.loads(line)["step"]["type"] for line in path.read_text(encoding="utf-8").splitlines()]
    assert recorded == ["item/completed", "error"]
