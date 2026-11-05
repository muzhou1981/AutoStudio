"""飞书会话与 Run 的临时绑定（入站文本 HITL）。"""

from __future__ import annotations

from threading import Lock

_lock = Lock()
_chat_to_thread: dict[str, str] = {}


def _key_chat(chat_id: str) -> str:
    return f"chat:{chat_id}"


def _key_open(open_id: str) -> str:
    return f"open:{open_id}"


def register_awaiting_thread(
    *,
    thread_id: str,
    chat_id: str = "",
    open_id: str = "",
) -> None:
    with _lock:
        if chat_id.strip():
            _chat_to_thread[_key_chat(chat_id.strip())] = thread_id
        if open_id.strip():
            _chat_to_thread[_key_open(open_id.strip())] = thread_id


def resolve_thread_id(*, chat_id: str = "", open_id: str = "") -> str | None:
    with _lock:
        if chat_id.strip():
            tid = _chat_to_thread.get(_key_chat(chat_id.strip()))
            if tid:
                return tid
        if open_id.strip():
            return _chat_to_thread.get(_key_open(open_id.strip()))
    return None


def clear_thread_bindings(thread_id: str) -> None:
    with _lock:
        drop = [k for k, v in _chat_to_thread.items() if v == thread_id]
        for k in drop:
            del _chat_to_thread[k]
