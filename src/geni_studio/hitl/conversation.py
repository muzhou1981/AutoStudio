"""把一轮里各节点的模型会话落到运行目录。

新运行按节点归档：`conversations/nodes/<节点>/<序号>.jsonl`，记录内含角色；
旧运行按角色归档的 `conversations/<角色>/` 仍可读取。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from geni_studio.config.context import factory_root
from geni_studio.hitl.choices import (
    answers_from_reply,
    choice_signature,
    extract_choice_groups,
    option_letter,
    plain_line,
)


def conversation_dir(thread_id: str, workspace_path: str = "") -> Path:
    """runs/<thread_id>/conversations。工作树在时写到目标项目，否则写到工厂目录。"""
    root = _run_root(thread_id, workspace_path)
    return root / "conversations"


def begin_turn(
    thread_id: str,
    role: str,
    *,
    agent_id: str,
    model: str,
    prompt: str,
    workspace_path: str = "",
    node: str | None = None,
) -> Path:
    if node is None:
        from geni_studio.backends.session import current_node_id

        node = current_node_id()
    base = conversation_dir(thread_id, workspace_path)
    folder = base / "nodes" / _safe(node) if node else base / _safe(role)
    folder.mkdir(parents=True, exist_ok=True)
    seq = 1
    while True:
        path = folder / f"{seq:03d}.jsonl"
        try:
            path.touch(exist_ok=False)
            break
        except FileExistsError:
            seq += 1
    _append(path, {
        "kind": "turn",
        "role": role,
        "node": node,
        "agent_id": agent_id,
        "model": model,
        "prompt": prompt,
    })
    return path


def append_step(path: Path, step: Any) -> None:
    _append(path, {"kind": "step", "step": step_to_dict(step)})


def finish_turn(path: Path, text: str) -> None:
    _append(path, {"kind": "result", "text": text})


def read_artifact_text(thread_id: str, key: str, *, workspace_path: str = "") -> str:
    """读取这一轮落盘的产物全文。没有文件时返回空字符串。"""
    if not key or "/" in key or "\\" in key or key.startswith("."):
        return ""
    root = _run_root(thread_id, workspace_path)
    for path in (root / "artifacts" / f"{key}.md", root / f"{key}.md"):
        if path.is_file():
            return path.read_text(encoding="utf-8")
    return ""


def node_role(values: dict[str, Any], node: str) -> str:
    """节点对应的角色：优先取运行状态里的流程节点表，默认图回退到内置映射。"""
    for item in values.get("workflow_nodes") or []:
        if isinstance(item, dict) and item.get("id") == node:
            return str(item.get("role") or "")
    from geni_studio.hitl.rail import NODE_ROLE

    return NODE_ROLE.get(node, "")


def conversation_view(
    thread_id: str,
    role: str = "",
    *,
    node: str = "",
    workspace_path: str = "",
) -> dict[str, Any]:
    """按节点读取会话；该节点没有按节点归档的记录时回退到旧的按角色目录。"""
    base = conversation_dir(thread_id, workspace_path)
    folder = base / "nodes" / _safe(node) if node else None
    if folder is None or not any(folder.glob("*.jsonl")):
        folder = base / _safe(role) if role else None
    turns: list[dict[str, Any]] = []
    if folder is not None and folder.is_dir():
        for path in sorted(folder.glob("*.jsonl")):
            events = _read_events(path)
            turns.append({"seq": path.stem, "events": events, "questions": turn_questions(events)})
    return {"role": role, "node": node, "turns": turns}


def turn_questions(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """本次回复里给人点选的题组；`hide` 是回复正文中已由题卡展示、无需重复渲染的原始行。"""
    text = _result_text(events)
    groups = extract_choice_groups(text)
    if not groups:
        return []
    out = []
    for group in groups:
        letters = {str(item["id"]) for item in group["choices"]}
        hide = [
            raw.strip()
            for raw in text.splitlines()
            if raw.strip()
            and (
                plain_line(raw) == plain_line(group.get("prompt") or "")
                or option_letter(raw) in letters
            )
        ]
        out.append({**group, "signature": choice_signature(group), "hide": hide})
    return out


def record_human_answer(
    thread_id: str,
    groups: list[dict[str, Any]],
    *,
    reply: str,
    decision: str,
    channel: str,
    actor: str = "",
    workspace_path: str = "",
) -> Path | None:
    """把人对题组的答复写回提出这些题的最近一次会话；该次会话已有答复时不再追加。"""
    wanted = {choice_signature(g) for g in groups if g.get("choices")}
    if not wanted:
        return None
    base = conversation_dir(thread_id, workspace_path)
    best: tuple[float, Path, list[dict[str, Any]]] | None = None
    for path in base.glob("**/*.jsonl"):
        events = _read_events(path)
        asked = turn_questions(events)
        if not any(g["signature"] in wanted for g in asked):
            continue
        if any(e.get("kind") == "human" for e in events):
            continue
        stamp = path.stat().st_mtime
        if best is None or stamp > best[0]:
            best = (stamp, path, asked)
    if best is None:
        return None
    _, path, asked = best
    _append(path, {
        "kind": "human",
        "at": datetime.now(UTC).isoformat(),
        "channel": channel,
        "actor": actor,
        "decision": decision,
        "reply": reply,
        "answers": answers_from_reply(asked, reply),
    })
    return path


def _result_text(events: list[dict[str, Any]]) -> str:
    for event in reversed(events):
        if event.get("kind") == "result":
            return str(event.get("text") or "")
    return ""


def _read_events(path: Path) -> list[dict[str, Any]]:
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def step_to_dict(step: Any) -> dict[str, Any]:
    if isinstance(step, dict):
        return {"type": str(step.get("type") or "step"), "message": _plain(step.get("message", step))}
    kind = str(getattr(step, "type", "step"))
    message = getattr(step, "message", None)
    return {"type": kind, "message": _plain(message if message is not None else step)}


def _run_root(thread_id: str, workspace_path: str) -> Path:
    from geni_studio.workspace.layout import run_dir_for_workspace

    found = run_dir_for_workspace(workspace_path, thread_id)
    if found is not None:
        return found
    return factory_root() / ".geni_studio" / "runs" / thread_id


def _safe(role: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in role.strip())
    return cleaned or "unknown"


def _append(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def _plain(value: Any, depth: int = 0) -> Any:
    if depth > 4 or value is None or isinstance(value, (str, int, float, bool)):
        if isinstance(value, str) and len(value) > 8000:
            return value[:8000] + "…"
        return value
    if isinstance(value, dict):
        return {str(key): _plain(item, depth + 1) for key, item in list(value.items())[:40]}
    if isinstance(value, (list, tuple)):
        return [_plain(item, depth + 1) for item in list(value)[:40]]
    if hasattr(value, "__dict__"):
        data = {
            key: _plain(item, depth + 1)
            for key, item in vars(value).items()
            if not str(key).startswith("_")
        }
        return data or str(value)[:8000]
    return str(value)[:8000]
