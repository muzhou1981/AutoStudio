"""飞书会话与 Run 的绑定（入站文本 HITL 与状态查询）。重启后仍保留。"""

from __future__ import annotations

import json
from threading import Lock

from geni_studio.config.context import factory_root

_lock = Lock()
_chat_to_threads: dict[str, list[str]] = {}
_MAX_THREADS = 8


def sessions_path():
    return factory_root() / "runs" / "feishu_sessions.json"


def _read() -> dict[str, list[str]]:
    path = sessions_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, list[str]] = {}
    for key, ids in data.items():
        if isinstance(ids, list):
            out[str(key)] = [str(item) for item in ids if str(item).strip()][:_MAX_THREADS]
    return out


def _write(data: dict[str, list[str]]) -> None:
    path = sessions_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _key_chat(chat_id: str) -> str:
    return f"chat:{chat_id}"


def _key_open(open_id: str) -> str:
    return f"open:{open_id}"


def _push(data: dict[str, list[str]], key: str, thread_id: str) -> None:
    current = [item for item in data.get(key, []) if item != thread_id]
    data[key] = [thread_id, *current][:_MAX_THREADS]


def register_awaiting_thread(
    *,
    thread_id: str,
    chat_id: str = "",
    open_id: str = "",
) -> None:
    with _lock:
        data = _read()
        if chat_id.strip():
            _push(data, _key_chat(chat_id.strip()), thread_id)
        if open_id.strip():
            _push(data, _key_open(open_id.strip()), thread_id)
        _chat_to_threads.clear()
        _chat_to_threads.update(data)
        _write(data)


def bound_thread_ids(*, chat_id: str = "", open_id: str = "") -> list[str]:
    """最近绑定在前。同一会话里优先用群，没有群再看单聊。"""
    with _lock:
        data = _read()
        if chat_id.strip():
            found = data.get(_key_chat(chat_id.strip()))
            if found:
                return list(found)
        if open_id.strip():
            return list(data.get(_key_open(open_id.strip()), []))
    return []


def resolve_thread_id(*, chat_id: str = "", open_id: str = "") -> str | None:
    ids = bound_thread_ids(chat_id=chat_id, open_id=open_id)
    return ids[0] if ids else None


def clear_thread_bindings(thread_id: str) -> None:
    with _lock:
        data = _read()
        for key, ids in list(data.items()):
            kept = [item for item in ids if item != thread_id]
            if kept:
                data[key] = kept
            else:
                del data[key]
        _chat_to_threads.clear()
        _chat_to_threads.update(data)
        _write(data)
