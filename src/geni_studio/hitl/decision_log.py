"""人在停点上的决定按次落盘，供运行页回看当时的待决内容与选择。

决策点批复、需求澄清答复与回退升级的选择都写在运行目录的 `decisions.jsonl`，
每条记在当时待办所在的格子名下。早于该文件的决策点批复只在 `baseline_log` 里留有
决定、时间与意见，读取时按同一决策点的先后顺序补齐。
"""

from __future__ import annotations

import ast
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from geni_studio.hitl.conversation import conversation_dir

_BASELINE = re.compile(
    r"^\[baseline:(?P<node>[^\]]+)\] decision=(?P<decision>\w+) at=(?P<at>\S+)(?: note=(?P<note>.*))?$"
)


def decisions_path(thread_id: str, workspace_path: str = "") -> Path:
    return conversation_dir(thread_id, workspace_path).parent / "decisions.jsonl"


def record_decision(
    thread_id: str,
    *,
    node: str,
    kind: str,
    summary: str,
    review: list[dict[str, Any]],
    decision: str,
    reply: str,
    channel: str,
    actor: str,
    questions: list[str] | None = None,
    reject_label: str = "",
    workspace_path: str = "",
) -> None:
    path = decisions_path(thread_id, workspace_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "at": datetime.now(UTC).isoformat(),
        "node": node,
        "kind": kind,
        "summary": summary,
        "questions": list(questions or []),
        "review": review,
        "decision": decision,
        "reject_label": reject_label,
        "reply": reply,
        "channel": channel,
        "actor": actor,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")


def node_decisions(
    thread_id: str,
    node: str,
    values: dict[str, Any],
    *,
    reject_label: str = "",
) -> list[dict[str, Any]]:
    """记在该格子名下的历次决定，按先后排列。"""
    recorded = [
        item for item in _read(decisions_path(thread_id, str(values.get("workspace_path") or "")))
        if item.get("node") == node
    ]
    gates = [item for item in recorded if item.get("kind", "gate") == "gate"]
    applied = [item for item in _baseline(str(values.get("baseline_log") or "")) if item["node"] == node]
    # 基线在决策点执行时才写，且只精确到秒；早于首条新记录所在那一秒的才是没有新记录的旧决定。
    first = min((_stamp(item.get("at")) for item in gates), default=None)
    legacy = [
        {**item, "reject_label": reject_label, "legacy": True}
        for item in applied
        if first is None or _stamp(item["at"]) < first
    ]
    return sorted(recorded + legacy, key=lambda item: _stamp(item.get("at")))


def _stamp(at: Any) -> str:
    try:
        when = datetime.fromisoformat(str(at))
    except ValueError:
        return str(at or "")
    return when.astimezone(UTC).replace(microsecond=0).isoformat()


def _baseline(log: str) -> list[dict[str, Any]]:
    out = []
    for line in log.splitlines():
        match = _BASELINE.match(line.strip())
        if not match:
            continue
        reply = ""
        if match.group("note"):
            try:
                reply = str(ast.literal_eval(match.group("note")))
            except (ValueError, SyntaxError):
                reply = match.group("note")
        out.append({
            "node": match.group("node"),
            "kind": "gate",
            "decision": match.group("decision"),
            "at": match.group("at"),
            "reply": reply,
        })
    return out


def _read(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            out.append(item)
    return out
