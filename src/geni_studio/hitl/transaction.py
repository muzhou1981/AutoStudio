"""对同一 Run 的变更串行化；等待时使用非阻塞锁，防止 HTTP 请求积压。"""

from __future__ import annotations

import threading
import weakref
from functools import wraps

_locks: weakref.WeakValueDictionary[str, threading.RLock] = weakref.WeakValueDictionary()
_guard = threading.Lock()


def run_mutation(fn):
    @wraps(fn)
    def wrapped(self, thread_id, *args, **kwargs):
        from geni_studio.hitl.service import RunBusy

        with _guard:
            lock = _locks.setdefault(thread_id, threading.RLock())
        if not lock.acquire(blocking=False):
            raise RunBusy("这一轮正在处理另一个请求，请刷新状态后再操作")
        try:
            return fn(self, thread_id, *args, **kwargs)
        finally:
            lock.release()
    return wrapped


def observation_mutation(fn):
    locked = run_mutation(fn)

    @wraps(fn)
    def wrapped(self, thread_id, *args, **kwargs):
        from geni_studio.hitl.service import RunBusy

        try:
            return locked(self, thread_id, *args, **kwargs)
        except RunBusy:
            # 观察请求仍可读检查点，但不能在执行中标记中断或写超时状态。
            return self.status(thread_id)
    return wrapped
