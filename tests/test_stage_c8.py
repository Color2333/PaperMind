"""C8：lease/fencing 与 Reconciler 测试

覆盖：过期 lease 回收（requeue/dead_letter 分流）、manual_recovery 能力不回队列、
迟到 Attempt 写入被拒（回收后旧 lease_token complete 抛 ConflictError）、
回收后重新领取签发新 fencing。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from packages.application.commands.reconciler import run_reconcile
from packages.domain.enums import JobStatus, TaskStatus
from packages.domain.exceptions import ConflictError
from packages.storage.db import session_scope
from packages.storage.models import DurableTask
from packages.storage.repositories import JobRepository, TaskRepository


def _make_leased_job_task(session, *, capability="skim_paper", max_attempts=2, timeout_s=600):
    job, _ = JobRepository(session).create_job(kind="RunTopicResearch")
    task, _ = TaskRepository(session).add_task(
        job_id=job.id, capability=capability, max_attempts=max_attempts, timeout_s=timeout_s
    )
    claimed = TaskRepository(session).claim_task_by_id(task_id=task.id, executor_id="exec-1")
    return job, task, claimed


def test_reconcile_requeues_expired_lease(isolated_db):
    with session_scope() as session:
        job, task, claimed = _make_leased_job_task(session)
        job_id = job.id
        task_id = claimed.id
        # 过期 120s（> backoff 60s）
        claimed.lease_expires_at = datetime.now(UTC) - timedelta(seconds=120)
        session.flush()

        summary = run_reconcile(session)
        assert summary["reclaimed"] == 1
        assert summary["outcomes"][task_id] == "requeued"

        refreshed = session.get(DurableTask, task_id)
        assert refreshed.status is TaskStatus.queued
        assert refreshed.lease_token is None
        # 重入队后 Job 活跃（active=1）→ running
        assert JobRepository(session).get(job_id).status is JobStatus.running


def test_reconcile_reclaims_within_backoff_window(isolated_db):
    """backoff 窗口内（过期 < backoff_s）不回收"""
    with session_scope() as session:
        job, task, claimed = _make_leased_job_task(session)
        claimed.lease_expires_at = datetime.now(UTC) - timedelta(seconds=10)
        session.flush()

        summary = run_reconcile(session, backoff_s=60)
        assert summary["reclaimed"] == 0
        refreshed = session.get(DurableTask, claimed.id)
        assert refreshed.status is TaskStatus.leased


def test_reconcile_dead_letter_after_attempts_exhausted(isolated_db):
    with session_scope() as session:
        job, task, claimed = _make_leased_job_task(session, max_attempts=1)
        job_id = job.id
        claimed.lease_expires_at = datetime.now(UTC) - timedelta(seconds=120)
        session.flush()

        summary = run_reconcile(session)
        assert summary["outcomes"][claimed.id] == "dead_letter"
        assert JobRepository(session).get(job_id).status is JobStatus.failed


def test_late_attempt_write_rejected_after_reclaim(isolated_db):
    """回收 + 重新领取后，旧 lease_token 的写入必须被拒（迟到 Attempt 不覆盖）"""
    with session_scope() as session:
        job, task, claimed = _make_leased_job_task(session)
        job_id = job.id
        task_id = claimed.id
        old_lease_token = claimed.lease_token
        claimed.lease_expires_at = datetime.now(UTC) - timedelta(seconds=120)
        session.flush()

        run_reconcile(session)
        # 回收后重新领取 → 新 lease token
        reclaimed = TaskRepository(session).claim_task_by_id(task_id=task_id, executor_id="exec-2")
        assert reclaimed.lease_token != old_lease_token

        # 旧 Attempt 迟到写入 → ConflictError
        with pytest.raises(ConflictError):
            TaskRepository(session).complete_task(
                task_id=task_id, executor_id="exec-1", lease_token=old_lease_token
            )
        # 新持有者写入成功
        done = TaskRepository(session).complete_task(
            task_id=task_id, executor_id="exec-2", lease_token=reclaimed.lease_token
        )
        assert done.status is TaskStatus.succeeded
        assert JobRepository(session).get(job_id).status is JobStatus.succeeded


def test_manual_recovery_capability_not_requeued(isolated_db):
    with session_scope() as session:
        # send_brief_email 在注册表中 manual_recovery=True
        job, task, claimed = _make_leased_job_task(session, capability="send_brief_email")
        claimed.lease_expires_at = datetime.now(UTC) - timedelta(seconds=120)
        session.flush()

        summary = run_reconcile(session)
        assert summary["manual_recovery"] == [claimed.id]
        refreshed = session.get(DurableTask, claimed.id)
        assert refreshed.status is TaskStatus.manual_recovery
