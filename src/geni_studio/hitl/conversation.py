"""把一轮里某个角色的 Cursor 会话落到运行目录。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from geni_studio.config.context import factory_root


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
) -> Path:
    folder = conversation_dir(thread_id, workspace_path) / _safe(role)
    folder.mkdir(parents=True, exist_ok=True)
    seq = len(list(folder.glob("*.jsonl"))) + 1
    path = folder / f"{seq:03d}.jsonl"
    _append(path, {
        "kind": "turn",
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
    path = _run_root(thread_id, workspace_path) / f"{key}.md"
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8")


def conversation_view(thread_id: str, role: str, *, workspace_path: str = "") -> dict[str, Any]:
    folder = conversation_dir(thread_id, workspace_path) / _safe(role)
    turns: list[dict[str, Any]] = []
    if folder.is_dir():
        for path in sorted(folder.glob("*.jsonl")):
            events = []
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
            turns.append({"seq": path.stem, "events": events})
    return {"role": role, "turns": turns}


def step_to_dict(step: Any) -> dict[str, Any]:
    if isinstance(step, dict):
        return {"type": str(step.get("type") or "step"), "message": _plain(step.get("message", step))}
    kind = str(getattr(step, "type", "step"))
    message = getattr(step, "message", None)
    return {"type": kind, "message": _plain(message if message is not None else step)}


def _run_root(thread_id: str, workspace_path: str) -> Path:
    worktree = Path(workspace_path) if workspace_path else None
    if worktree is not None and worktree.parent.name == "worktrees":
        dot = worktree.parent.parent
        if dot.name == ".geni_studio":
            return dot / "runs" / thread_id
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
