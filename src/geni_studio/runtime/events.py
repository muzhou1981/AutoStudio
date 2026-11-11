"""进程内的运行变更版本号，供状态推送判断是否需要重新读取。"""

from __future__ import annotations

import threading

_lock = threading.Lock()
_versions: dict[str, int] = {}
_MAX_TRACKED = 4096


def bump(thread_id: str) -> None:
    if not thread_id:
        return
    with _lock:
        if thread_id not in _versions and len(_versions) >= _MAX_TRACKED:
            _versions.pop(next(iter(_versions)))
        _versions[thread_id] = _versions.get(thread_id, 0) + 1


def version(thread_id: str) -> int:
    with _lock:
        return _versions.get(thread_id, 0)
