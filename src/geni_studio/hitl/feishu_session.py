"""飞书会话与 Run 的临时绑定（入站文本 HITL 与状态查询）。"""

from __future__ import annotations

from threading import Lock

_lock = Lock()
_chat_to_threads: dict[str, list[str]] = {}
_MAX_THREADS = 8


def _key_chat(chat_id: str) -> str:
    return f"chat:{chat_id}"


def _key_open(open_id: str) -> str:
    return f"open:{open_id}"


def _push(key: str, thread_id: str) -> None:
    current = [item for item in _chat_to_threads.get(key, []) if item != thread_id]
    _chat_to_threads[key] = [thread_id, *current][:_MAX_THREADS]


def register_awaiting_thread(
    *,
    thread_id: str,
    chat_id: str = "",
    open_id: str = "",
) -> None:
    with _lock:
        if chat_id.strip():
            _push(_key_chat(chat_id.strip()), thread_id)
        if open_id.strip():
            _push(_key_open(open_id.strip()), thread_id)


def bound_thread_ids(*, chat_id: str = "", open_id: str = "") -> list[str]:
    """最近绑定在前。同一会话里优先用群，没有群再看单聊。"""
    with _lock:
        if chat_id.strip():
            found = _chat_to_threads.get(_key_chat(chat_id.strip()))
            if found:
                return list(found)
        if open_id.strip():
            return list(_chat_to_threads.get(_key_open(open_id.strip()), []))
    return []


def resolve_thread_id(*, chat_id: str = "", open_id: str = "") -> str | None:
    ids = bound_thread_ids(chat_id=chat_id, open_id=open_id)
    return ids[0] if ids else None


def clear_thread_bindings(thread_id: str) -> None:
    with _lock:
        for key, ids in list(_chat_to_threads.items()):
            kept = [item for item in ids if item != thread_id]
            if kept:
                _chat_to_threads[key] = kept
            else:
                del _chat_to_threads[key]
