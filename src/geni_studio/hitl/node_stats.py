"""按流程节点汇总历次运行：执行次数、耗时、回退、升级、驳回与用量。只读，见 ADR 0030。"""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any

from geni_studio.hitl.conversation import conversation_dir
from geni_studio.hitl.decision_log import decisions_path


def _blank() -> dict[str, Any]:
    return {
        "runs": 0,
        "turns": 0,
        "avg_seconds": None,
        "returns": 0,
        "escalations": 0,
        "rejections": 0,
        "input_tokens": 0,
        "output_tokens": 0,
    }


def top_level_node(flat_id: str, node_ids: Iterable[str]) -> str:
    """子图与并行展开后的标识形如“顶层标识__…”，归到最长匹配的顶层节点。"""
    best = ""
    for node_id in node_ids:
        if (flat_id == node_id or flat_id.startswith(node_id + "__")) and len(node_id) > len(best):
            best = node_id
    return best


def _time(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return rows
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def workflow_node_stats(
    records: Iterable[tuple[str, dict[str, Any]]], workflow_id: str, node_ids: list[str]
) -> dict[str, Any]:
    nodes = {node_id: _blank() for node_id in node_ids}
    seconds = {node_id: [0.0, 0] for node_id in node_ids}
    runs = 0
    for thread_id, values in records:
        if values.get("workflow_id") != workflow_id:
            continue
        runs += 1
        touched: set[str] = set()
        for flat, count in (values.get("return_counts") or {}).items():
            top = top_level_node(str(flat), node_ids)
            if top and int(count or 0) > 0:
                nodes[top]["returns"] += int(count)
                touched.add(top)
        workspace = str(values.get("workspace_path") or "")
        folder = conversation_dir(thread_id, workspace) / "nodes"
        for node_dir in sorted(folder.iterdir()) if folder.is_dir() else []:
            top = top_level_node(node_dir.name, node_ids)
            if not top:
                continue
            for path in sorted(node_dir.glob("*.jsonl")):
                rows = _jsonl(path)
                turn = next((row for row in rows if row.get("kind") == "turn"), None)
                if turn is None:
                    continue
                item = nodes[top]
                item["turns"] += 1
                touched.add(top)
                result = next((row for row in rows if row.get("kind") == "result"), None)
                if result is None:
                    continue
                began, ended = _time(turn.get("at")), _time(result.get("at"))
                if began and ended and ended >= began:
                    seconds[top][0] += (ended - began).total_seconds()
                    seconds[top][1] += 1
                usage = result.get("usage") if isinstance(result.get("usage"), dict) else {}
                item["input_tokens"] += int(usage.get("input_tokens") or 0)
                item["output_tokens"] += int(usage.get("output_tokens") or 0)
        for entry in _jsonl(decisions_path(thread_id, workspace)):
            top = top_level_node(str(entry.get("node") or ""), node_ids)
            if not top:
                continue
            touched.add(top)
            if entry.get("kind") == "escalation":
                nodes[top]["escalations"] += 1
            elif entry.get("kind") == "gate" and entry.get("decision") == "rejected":
                nodes[top]["rejections"] += 1
        for top in touched:
            nodes[top]["runs"] += 1
    for node_id, (total, count) in seconds.items():
        if count:
            nodes[node_id]["avg_seconds"] = round(total / count, 1)
    return {"runs": runs, "nodes": nodes}
