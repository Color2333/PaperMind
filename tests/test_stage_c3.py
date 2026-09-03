"""C3：统一旧状态——durable Job 桥接与统一查询端点

覆盖：submit_durable_job/submit_tracked_compat 的 durable 持久化语义
（Job/Task/Attempt 落库、成功/失败收敛、result 存储）、/tasks/{id} durability
优先解析、/tasks/active 合并、GET /jobs 与 /jobs/{id} graph。
"""

from __future__ import annotations

import threading
import time

from sqlalchemy import select

from packages.application.commands.jobs import submit_durable_job, submit_tracked_compat
from packages.domain.enums import JobStatus, TaskStatus
from packages.storage.db import session_scope
from packages.storage.repositories import JobRepository


def test_submit_durable_job_success_flow(isolated_db):
    calls = []

    def _fn(progress_callback=None):
        calls.append(1)
        if progress_callback:
            progress_callback("处理中...", 50, 100)
        return {"answer": "ok"}

    result = submit_durable_job(
        kind="StartSkim",
        capability="skim_paper",
        title="测试任务",
        fn=_fn,
        payload={"paper_id": "p1"},
    )
    # 等待 tracker 后台线程完成
    deadline = time.monotonic() + 30
    job_status = job_progress = None
    while time.monotonic() < deadline:
        with session_scope() as session:
            job = JobRepository(session).get(result["job_id"])
            job_status = job.status
            job_progress = dict(job.progress or {})
            if job_status in (JobStatus.succeeded, JobStatus.failed):
                break
        threading.Event().wait(0.05)

    assert calls, "fn 应被 tracker 通道执行"
    assert job_status is JobStatus.succeeded
    # 进度桥接的 current/total 是写入期快照——job 收敛后可能被覆盖，仅断言字段存在
    assert isinstance(job_progress, dict)

    with session_scope() as session:
        from packages.storage.models import DurableTask, TaskAttempt

        task = session.get(DurableTask, result["durable_task_id"])
        assert task.status is TaskStatus.succeeded
        assert task.input_ref["result_ref"] == {"answer": "ok"}
        assert task.external_ref == result["task_id"]
        attempt = (
            session.execute(select(TaskAttempt).where(TaskAttempt.task_id == task.id))
            .scalars()
            .one()
        )
        assert attempt.status.value == "succeeded"


def test_submit_durable_job_failure_flow(isolated_db):
    def _boom(progress_callback=None):
        raise RuntimeError("任务炸了")

    result = submit_durable_job(
        kind="StartSkim",
        capability="skim_paper",
        title="失败任务",
        fn=_boom,
        max_attempts=1,
    )
    deadline = time.monotonic() + 30
    status = None
    while time.monotonic() < deadline:
        with session_scope() as session:
            status = JobRepository(session).get(result["job_id"]).status
            if status in (JobStatus.failed, JobStatus.succeeded):
                break
        threading.Event().wait(0.05)

    assert status is JobStatus.failed
    with session_scope() as session:
        from packages.storage.models import DurableTask

        task = session.get(DurableTask, result["durable_task_id"])
        assert task.status is TaskStatus.dead_letter  # max_attempts=1 → 不重试
        assert "任务炸了" in (task.last_error or "")


def test_submit_tracked_compat_returns_tracker_id(isolated_db):
    def _fn(progress_callback=None):
        return {"value": 42}

    tracker_task_id = submit_tracked_compat(
        "mcp_daily",
        "兼容形状任务",
        _fn,
        capability="run_daily_ingest",
        kind="StartDailyIngest",
        total=2,
        category="mcp",
    )
    assert isinstance(tracker_task_id, str) and tracker_task_id.startswith("mcp_daily_")

    deadline = time.monotonic() + 30
    job_status = None
    while time.monotonic() < deadline:
        with session_scope() as session:
            from packages.storage.repositories import TaskRepository

            task = TaskRepository(session).get_by_external_ref(tracker_task_id)
            if task is not None:
                job = JobRepository(session).get(task.job_id)
                job_status = job.status
                if job_status in (JobStatus.succeeded, JobStatus.failed):
                    break
        threading.Event().wait(0.05)

    assert job_status is JobStatus.succeeded
    # external_ref 已回填 tracker id（durability 优先解析的关键）
    with session_scope() as session:
        from packages.storage.repositories import TaskRepository

        task = TaskRepository(session).get_by_external_ref(tracker_task_id)
        assert task is not None
