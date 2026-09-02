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


def _run_one_job(job_id: str, kind: str, paper_ids: list[str]) -> None:
    """执行单条 batch job（入参为纯值——claim 事务提交后 ORM 对象已脱管过期）"""
    pipelines = PaperPipelines()
    for pid_str in paper_ids:
        if _stop.is_set():
            break
        try:
            pid = UUID(pid_str)
            if kind == "skim":
                pipelines.skim(pid)
            elif kind == "deep_read":
                pipelines.deep_dive(pid)
            elif kind == "embed":
                pipelines.embed_paper(pid)
            with session_scope() as s:
                BatchJobRepository(s).mark_progress(job_id, done_delta=1)
        except Exception as exc:
            logger.warning("batch job %s paper %s failed: %s", job_id, pid_str, exc)
            with session_scope() as s:
                BatchJobRepository(s).mark_progress(
                    job_id, failed_delta=1, error_patch={pid_str: str(exc)[:300]}
                )


def poll_once() -> bool:
    """领取并处理一条 batch job（含收尾）。返回是否消费到任务。

    抽出为独立函数：_consumer_loop 的循环体 + 测试/运维单步执行复用。
    """
    with session_scope() as s:
        job = BatchJobRepository(s).claim_next()
        if job is None:
            return False
        # session 提交即过期：在事务内取出纯值，避免脱管访问（存量 DetachedInstanceError）
        job_id = job.id
        kind = job.kind
        paper_ids = list(job.paper_ids or [])
    _run_one_job(job_id, kind, paper_ids)
    with session_scope() as s:
        BatchJobRepository(s).mark_finished(job_id, "completed")
    return True


def _consumer_loop() -> None:
    while not _stop.is_set():
        try:
            if not poll_once():
                _stop.wait(_POLL_INTERVAL)
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
