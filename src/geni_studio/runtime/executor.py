"""运行执行器：从任务表领取任务并推进图，与 HTTP 请求解耦。

默认随 Web 进程启动；设置 `GENI_STUDIO_EXECUTOR=external` 时 Web 只入队，
由 `geni-studio-worker` 独立进程执行。
"""

from __future__ import annotations

import logging
import os
import threading
from typing import TYPE_CHECKING

from geni_studio.runtime.store import Job, worker_id

if TYPE_CHECKING:
    from geni_studio.hitl.service import GraphRunService

logger = logging.getLogger(__name__)

WRITE_BUSY_RETRY_SECONDS = 5.0
RUN_BUSY_RETRY_SECONDS = 0.2


def executor_mode() -> str:
    """`inline`：入队后在当前线程执行（测试与命令行）；`thread`：本进程后台执行；`external`：只入队。"""
    raw = os.environ.get("GENI_STUDIO_EXECUTOR", "").strip().lower()
    if raw in {"inline", "thread", "external"}:
        return raw
    if os.environ.get("GENI_STUDIO_SYNC_START", "").strip().lower() in ("1", "true", "yes"):
        return "inline"
    return "thread"


def _workers() -> int:
    raw = os.environ.get("GENI_STUDIO_EXECUTOR_WORKERS", "").strip()
    try:
        value = int(raw) if raw else 4
    except ValueError:
        value = 4
    return max(1, min(value, 32))


class Executor:
    def __init__(self, service: GraphRunService, *, workers: int | None = None, poll_seconds: float = 0.5) -> None:
        self.service = service
        self.store = service.runtime_store()
        self.worker = worker_id()
        self._workers = workers or _workers()
        self._poll = poll_seconds
        self._wake = threading.Event()
        self._stopping = threading.Event()
        self._threads: list[threading.Thread] = []

    # --- 生命周期 ---

    def start(self) -> None:
        if self._threads:
            return
        self.recover()
        for index in range(self._workers):
            thread = threading.Thread(target=self._loop, name=f"geni-exec-{index}", daemon=True)
            thread.start()
            self._threads.append(thread)
        keeper = threading.Thread(target=self._housekeeping, name="geni-exec-keeper", daemon=True)
        keeper.start()
        self._threads.append(keeper)

    def stop(self, timeout: float = 5.0) -> None:
        self._stopping.set()
        self._wake.set()
        for thread in self._threads:
            thread.join(timeout)
        self._threads.clear()

    def wake(self) -> None:
        self._wake.set()

    def recover(self) -> list[Job]:
        """进程重启后：执行进程已退出的任务记为失败，对应轮次标记中断。"""
        orphans = self.store.recover_orphans()
        for job in orphans:
            self.service.mark_interrupted_after_crash(job.thread_id)
        return orphans

    # --- 执行 ---

    def run_once(self, *, job_id: int | None = None) -> Job | None:
        job = self.store.claim(self.worker, job_id=job_id)
        if job is None:
            return None
        self._execute(job)
        return job

    def _execute(self, job: Job) -> None:
        from geni_studio.hitl.service import RunBusy
        from geni_studio.workspace.policy import WriteBusy

        try:
            self.service.execute_job(job)
        except RunBusy:
            self.store.defer(job.id, seconds=RUN_BUSY_RETRY_SECONDS, note="")
            return
        except WriteBusy as exc:
            self.store.defer(job.id, seconds=WRITE_BUSY_RETRY_SECONDS, note=f"等待写锁：{exc}")
            self.service.notify_change(job.thread_id)
            return
        except Exception as exc:
            logger.exception("运行任务失败 thread=%s kind=%s", job.thread_id, job.kind)
            self.store.finish(job.id, error=str(exc) or type(exc).__name__)
            self.service.after_job(job.thread_id, notify=False)
            return
        self.store.finish(job.id)
        self.service.after_job(job.thread_id)

    def _loop(self) -> None:
        while not self._stopping.is_set():
            try:
                job = self.run_once()
            except Exception:
                logger.exception("执行器领取任务失败")
                job = None
            if job is None:
                self._wake.wait(self._poll)
                self._wake.clear()

    def _housekeeping(self) -> None:
        last_sweep = 0.0
        import time

        while not self._stopping.wait(1.0):
            try:
                self.apply_controls()
                now = time.monotonic()
                if now - last_sweep >= 30:
                    last_sweep = now
                    self.recover()
                    self.service.sweep()
            except Exception:
                logger.exception("执行器巡检失败")

    def apply_controls(self) -> None:
        """把其他进程写入的停止、暂停请求同步到本进程正在执行的轮次。"""
        from geni_studio.hitl.control import (
            cancel_active_runs,
            request_pause,
            request_stop,
        )

        for thread_id in self.store.running_threads(self.worker):
            stop, pause = self.store.controls(thread_id)
            if stop:
                request_stop(thread_id)
                cancel_active_runs(thread_id)
            elif pause:
                request_pause(thread_id)


def main() -> None:
    """独立执行进程入口：`geni-studio-worker`。"""
    import signal

    from geni_studio.config.env_loader import apply_env_file
    from geni_studio.hitl.service import GraphRunService
    from geni_studio.workflows.default import get_graph

    logging.basicConfig(level=logging.INFO)
    apply_env_file()
    os.environ["GENI_STUDIO_EXECUTOR"] = "thread"
    executor = Executor(GraphRunService(get_graph()))
    done = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: done.set())
    signal.signal(signal.SIGINT, lambda *_: done.set())
    executor.start()
    logger.info("geni-studio-worker 已启动 worker=%s", executor.worker)
    done.wait()
    executor.stop()
