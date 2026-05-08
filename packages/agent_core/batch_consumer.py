"""
批量任务消费者 - daemon thread 处理 batch_jobs 队列
@author Color2333
"""

from __future__ import annotations

import logging
import threading
from uuid import UUID

from packages.ai.pipelines import PaperPipelines
from packages.storage.db import session_scope
from packages.storage.repositories import BatchJobRepository

logger = logging.getLogger(__name__)

_thread: threading.Thread | None = None
_stop = threading.Event()
_POLL_INTERVAL = 5.0


def _run_one_job(job) -> None:
    pipelines = PaperPipelines()
    for pid_str in job.paper_ids:
        if _stop.is_set():
            break
        try:
            pid = UUID(pid_str)
            if job.kind == "skim":
                pipelines.skim(pid)
            elif job.kind == "deep_read":
                pipelines.deep_dive(pid)
            elif job.kind == "embed":
                pipelines.embed_paper(pid)
            with session_scope() as s:
                BatchJobRepository(s).mark_progress(job.id, done_delta=1)
        except Exception as exc:
            logger.warning("batch job %s paper %s failed: %s", job.id, pid_str, exc)
            with session_scope() as s:
                BatchJobRepository(s).mark_progress(
                    job.id, failed_delta=1, error_patch={pid_str: str(exc)[:300]}
                )


def _consumer_loop() -> None:
    while not _stop.is_set():
        try:
            with session_scope() as s:
                job = BatchJobRepository(s).claim_next()
            if job is None:
                _stop.wait(_POLL_INTERVAL)
                continue
            _run_one_job(job)
            with session_scope() as s:
                BatchJobRepository(s).mark_finished(job.id, "completed")
        except Exception:
            logger.exception("batch consumer loop error")
            _stop.wait(_POLL_INTERVAL)


def start() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    with session_scope() as s:
        BatchJobRepository(s).recover_stale_running()
    _thread = threading.Thread(target=_consumer_loop, daemon=True, name="batch-consumer")
    _thread.start()
    logger.info("batch consumer thread started")


def stop() -> None:
    _stop.set()
