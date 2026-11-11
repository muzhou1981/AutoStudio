"""内容寻址快照：角色正文、流程定义等大块只读内容按哈希存放一次，运行状态只保留引用。

文件位于检查点库同目录的 `snapshots/<sha256>.json`；内存检查点对应进程内字典。
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from collections import OrderedDict
from copy import deepcopy
from pathlib import Path
from typing import Any

_PREFIX = "sha256:"
_CACHE_SIZE = 128
_memory: dict[str, Any] = {}
_cache: OrderedDict[str, Any] = OrderedDict()
_lock = threading.Lock()


class SnapshotMissing(KeyError):
    pass


def _directory() -> Path | None:
    from geni_studio.workspace.checkpoint import checkpoint_file

    path = checkpoint_file()
    return None if path is None else path.parent / "snapshots"


def _encode(obj: Any) -> bytes:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def is_ref(value: Any) -> bool:
    return isinstance(value, str) and value.startswith(_PREFIX)


def put(obj: Any) -> str:
    data = _encode(obj)
    digest = hashlib.sha256(data).hexdigest()
    ref = _PREFIX + digest
    directory = _directory()
    if directory is None:
        with _lock:
            _memory.setdefault(ref, json.loads(data))
        return ref
    target = directory / f"{digest}.json"
    if not target.is_file():
        directory.mkdir(parents=True, exist_ok=True)
        tmp = directory / f".{digest}.{os.getpid()}.{threading.get_ident()}.tmp"
        tmp.write_bytes(data)
        os.replace(tmp, target)
    return ref


def get(ref: str) -> Any:
    """按引用读取快照；返回副本，调用方可以修改。"""
    if not is_ref(ref):
        raise SnapshotMissing(ref)
    with _lock:
        if ref in _cache:
            _cache.move_to_end(ref)
            return deepcopy(_cache[ref])
        if ref in _memory:
            return deepcopy(_memory[ref])
    directory = _directory()
    digest = ref[len(_PREFIX) :]
    path = None if directory is None else directory / f"{digest}.json"
    if path is None or not path.is_file():
        raise SnapshotMissing(ref)
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise SnapshotMissing(f"{ref}（内容校验失败）")
    value = json.loads(data)
    with _lock:
        _cache[ref] = value
        while len(_cache) > _CACHE_SIZE:
            _cache.popitem(last=False)
    return deepcopy(value)
