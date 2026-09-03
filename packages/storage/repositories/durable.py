"""原子 durable execution 仓储（C2，设计③ §1/§2）

职责边界：
- Job 的创建幂等（idempotency_key）；Job 状态由子 Task 收敛（recompute_job_status），
  业务代码不得手写 Job 终态（Reconciler 的职责在 C8 扩展）。
- Task 领取即签发 lease（token + 过期时间 + attempt 行 + fencing token）；
  complete/fail 校验 lease 持有者（fencing 最简形态；完整 lease 过期回收在 C8）。
- fail 按 max_attempts 决定重入队（attempt_count<max）或 dead_letter；
  attempt_count 达标后再次失败 → dead_letter。
- 领取支持 PG `FOR UPDATE SKIP LOCKED`；SQLite 走单 Dispatcher 串行（设计③ §5）。
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import func, select

from packages.domain.enums import (
    JobStatus,
    TaskAttemptStatus,
    TaskStatus,
)
from packages.domain.exceptions import ConflictError, NotFoundError

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from packages.storage.models import (
    DurableTask,
    Job,
    TaskArtifact,
    TaskAttempt,
)

_LEASE_BASE_S = 600


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _lease_expiry() -> datetime:
    return _utcnow() + timedelta(seconds=_LEASE_BASE_S)


class JobRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_job(
        self,
        *,
        kind: str,
        payload: dict | None = None,
        idempotency_key: str | None = None,
        priority: int = 0,
        budget: dict | None = None,
        research_run_id: str | None = None,
        created_by: str = "system",
    ) -> tuple[Job, bool]:
        """创建 Job；idempotency_key 命中时返回既有 Job（created=False）"""
        if idempotency_key:
            existing = self.session.execute(
                select(Job).where(Job.idempotency_key == idempotency_key)
            ).scalar_one_or_none()
            if existing is not None:
                return existing, False
        job = Job(
            kind=kind,
            payload=payload or {},
            idempotency_key=idempotency_key,
            priority=priority,
            budget=budget or {},
            research_run_id=research_run_id,
            created_by=created_by,
            status=JobStatus.queued,
        )
        self.session.add(job)
        self.session.flush()
        return job, True

    def get(self, job_id: str) -> Job:
        job = self.session.get(Job, job_id)
        if job is None:
            raise NotFoundError(f"Job {job_id} not found")
        return job

    def list_jobs(
        self, *, status: JobStatus | None = None, kind: str | None = None, limit: int = 100
    ) -> list[Job]:
        q = select(Job).order_by(Job.id.desc()).limit(limit)
        if status is not None:
            q = q.where(Job.status == status)
        if kind is not None:
            q = q.where(Job.kind == kind)
        return list(self.session.execute(q).scalars())

    def set_status(self, job_id: str, status: JobStatus) -> Job:
        """仅用于 submitted→planning→queued→running→cancelling 等过程态；
        终态（succeeded/partially_succeeded/failed/cancelled）走 recompute_job_status"""
        job = self.get(job_id)
        job.status = status
        if status is JobStatus.running and job.started_at is None:
            job.started_at = _utcnow()
        self.session.flush()
        return job

    def update_progress(self, job_id: str, *, current: int, total: int, message: str = "") -> None:
        """聚合进度（由子 Task 的执行进度写入，展示用；不改状态）"""
        job = self.get(job_id)
        job.progress = {"current": current, "total": total, "message": message}
        self.session.flush()

    def recompute_job_status(self, job_id: str) -> Job:
        """Job 状态由子 Task 收敛（设计③ §2：不得由 Executor 手写终态）"""
        job = self.get(job_id)
        rows = self.session.execute(
            select(DurableTask.status, func.count())
            .where(DurableTask.job_id == job_id)
            .group_by(DurableTask.status)
        ).all()
        counts = {str(status): int(n) for status, n in rows}
        total = sum(counts.values())
        if total == 0:
            return job  # 尚未展开 Task——保持当前过程态
        terminal_bad = counts.get(TaskStatus.failed.value, 0) + counts.get(
            TaskStatus.dead_letter.value, 0
        )
        succeeded = counts.get(TaskStatus.succeeded.value, 0)
        cancelled = counts.get(TaskStatus.cancelled.value, 0)
        active = total - terminal_bad - succeeded - cancelled

        now = _utcnow()
        job.finished_at = None
        if active > 0:
            job.status = JobStatus.running
            return job
        # 无活跃 Task：全部到达终态
        if terminal_bad == 0 and cancelled == 0:
            job.status = JobStatus.succeeded
            job.finished_at = now
        elif cancelled > 0 and terminal_bad == 0:
            job.status = JobStatus.cancelled
            job.finished_at = now
        elif succeeded > 0 and terminal_bad > 0:
            job.status = JobStatus.partially_succeeded
            job.finished_at = now
        else:
            job.status = JobStatus.failed
            job.finished_at = now
        return job


class TaskRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add_task(
        self,
        *,
        job_id: str,
        capability: str,
        input_ref: dict | None = None,
        idempotency_key: str | None = None,
        depends_on: list[str] | None = None,
        seq: int = 0,
        priority: int = 0,
        resource_class: str = "default",
        timeout_s: int = 600,
        max_attempts: int = 3,
        handler_version: int = 1,
        input_schema_version: int = 1,
        external_ref: str | None = None,
    ) -> tuple[DurableTask, bool]:
        """向 Job 展开 Task；idempotency_key 命中返回既有 Task（created=False）"""
        if idempotency_key:
            existing = self.session.execute(
                select(DurableTask).where(DurableTask.idempotency_key == idempotency_key)
            ).scalar_one_or_none()
            if existing is not None:
                return existing, False
        task = DurableTask(
            job_id=job_id,
            seq=seq,
            capability=capability,
            input_ref=input_ref or {},
            idempotency_key=idempotency_key,
            depends_on=depends_on or [],
            priority=priority,
            resource_class=resource_class,
            timeout_s=timeout_s,
            max_attempts=max_attempts,
            handler_version=handler_version,
            input_schema_version=input_schema_version,
            external_ref=external_ref,
            status=TaskStatus.queued,
        )
        self.session.add(task)
        self.session.flush()
        return task, True

    def get(self, task_id: str) -> DurableTask:
        task = self.session.get(DurableTask, task_id)
        if task is None:
            raise NotFoundError(f"Task {task_id} not found")
        return task

    def list_for_job(self, job_id: str) -> list[DurableTask]:
        return list(
            self.session.execute(
                select(DurableTask)
                .where(DurableTask.job_id == job_id)
                .order_by(DurableTask.seq, DurableTask.id)
            ).scalars()
        )

    def get_by_external_ref(self, external_ref: str) -> DurableTask | None:
        """按过渡期引用（tracker task_id / Go task id）解析 Task"""
        return self.session.execute(
            select(DurableTask).where(DurableTask.external_ref == external_ref)
        ).scalar_one_or_none()

    def touch_lease(self, task_id: str, lease_token: str) -> bool:
        """续约 lease（progress 事件时调用，防长任务租期过期）；返回是否成功"""
        task = self.get(task_id)
        if task.lease_token != lease_token:
            return False
        task.lease_expires_at = _utcnow() + timedelta(seconds=task.timeout_s or _LEASE_BASE_S)
        self.session.flush()
        return True

    def set_external_ref(self, task_id: str, external_ref: str) -> None:
        task = self.get(task_id)
        task.external_ref = external_ref
        self.session.flush()

    def claim_task(
        self, *, executor_id: str, capabilities: list[str], resource_class: str | None = None
    ) -> DurableTask | None:
        """领取一个匹配能力且依赖已满足的 queued Task；签发 lease + attempt + fencing。

        PG 用 skip_locked 行锁；SQLite（无行锁语义）靠单 Dispatcher 串行。
        """
        wanted = set(capabilities)
        q = (
            select(DurableTask)
            .where(DurableTask.status == TaskStatus.queued)
            .order_by(DurableTask.priority.desc(), DurableTask.seq, DurableTask.id)
        )
        if resource_class:
            q = q.where(DurableTask.resource_class == resource_class)
        if hasattr(q, "with_for_update"):
            q = q.with_for_update(skip_locked=True)
        candidates = list(self.session.execute(q.limit(50)).scalars())

        job_ids = {t.job_id for t in candidates}
        depends_done: dict[str, set[str]] = {}
        for jid in job_ids:
            succeeded = set(
                self.session.execute(
                    select(DurableTask.id).where(
                        DurableTask.job_id == jid,
                        DurableTask.status == TaskStatus.succeeded,
                    )
                ).scalars()
            )
            depends_done[jid] = succeeded

        now = _utcnow()
        for task in candidates:
            if task.capability not in wanted:
                continue
            deps = set(task.depends_on or [])
            if deps and not deps <= depends_done.get(task.job_id, set()):
                continue
            # 签发 lease + fencing token（= attempt_count+1）
            task.status = TaskStatus.leased
            task.attempt_count += 1
            task.lease_token = secrets.token_hex(16)
            task.lease_expires_at = now + timedelta(seconds=task.timeout_s or _LEASE_BASE_S)
            attempt = TaskAttempt(
                task_id=task.id,
                attempt_no=task.attempt_count,
                executor_id=executor_id,
                fencing_token=task.attempt_count,
                status=TaskAttemptStatus.running,
            )
            self.session.add(attempt)
            self.session.flush()
            # Job 进入 running
            JobRepository(self.session).set_status(task.job_id, JobStatus.running)
            return task
        return None

    def claim_task_by_id(self, *, task_id: str, executor_id: str) -> DurableTask:
        """领取指定 Task（fn 与 Task 绑定的入口用此语义，不做工作窃取）。

        仅 queued 可领取；签发 lease + attempt + fencing（复用 claim_task 的签发逻辑）。
        """
        task = self.get(task_id)
        if task.status is not TaskStatus.queued:
            raise ConflictError(f"Task {task_id} 状态 {task.status} 不可领取")
        task.status = TaskStatus.leased
        task.attempt_count += 1
        task.lease_token = secrets.token_hex(16)
        task.lease_expires_at = _utcnow() + timedelta(seconds=task.timeout_s or _LEASE_BASE_S)
        attempt = TaskAttempt(
            task_id=task.id,
            attempt_no=task.attempt_count,
            executor_id=executor_id,
            fencing_token=task.attempt_count,
            status=TaskAttemptStatus.running,
        )
        self.session.add(attempt)
        self.session.flush()
        JobRepository(self.session).set_status(task.job_id, JobStatus.running)
        return task

    def _check_lease(self, task: DurableTask, executor_id: str, lease_token: str) -> None:
        """fencing 最简形态：lease 持有者必须匹配（C8 扩展租期过期回收）"""
        if task.status not in (TaskStatus.leased, TaskStatus.running):
            raise ConflictError(f"Task {task.id} 状态 {task.status} 不可提交")
        if task.lease_token != lease_token or (
            task.lease_expires_at and task.lease_expires_at.replace(tzinfo=UTC) < _utcnow()
        ):
            raise ConflictError(f"Task {task.id} lease 已失效（迟到写入被拒绝）")

    def _running_attempt(self, task_id: str, fencing_token: int) -> TaskAttempt | None:
        return self.session.execute(
            select(TaskAttempt).where(
                TaskAttempt.task_id == task_id,
                TaskAttempt.fencing_token == fencing_token,
                TaskAttempt.status == TaskAttemptStatus.running,
            )
        ).scalar_one_or_none()

    def complete_task(
        self,
        *,
        task_id: str,
        executor_id: str,
        lease_token: str,
        result_ref: dict | None = None,
    ) -> DurableTask:
        task = self.get(task_id)
        self._check_lease(task, executor_id, lease_token)
        fencing = task.attempt_count
        task.status = TaskStatus.succeeded
        task.lease_token = None
        task.lease_expires_at = None
        attempt = self._running_attempt(task_id, fencing)
        if attempt is not None:
            attempt.status = TaskAttemptStatus.succeeded
            attempt.finished_at = _utcnow()
        if result_ref:
            task.input_ref = {**(task.input_ref or {}), "result_ref": result_ref}
        self.session.flush()
        JobRepository(self.session).recompute_job_status(task.job_id)
        return task

    def fail_task(
        self,
        *,
        task_id: str,
        executor_id: str,
        lease_token: str,
        error_class: str = "unknown",
        message: str = "",
    ) -> DurableTask:
        """失败：attempt<max 重入队（backoff 由 Dispatcher 决定），否则 dead_letter"""
        task = self.get(task_id)
        self._check_lease(task, executor_id, lease_token)
        fencing = task.attempt_count
        task.last_error = f"[{error_class}] {message}"[:2000]
        attempt = self._running_attempt(task_id, fencing)
        if attempt is not None:
            attempt.status = TaskAttemptStatus.failed
            attempt.error_class = error_class
            attempt.error_message = message[:2000]
            attempt.finished_at = _utcnow()

        if task.attempt_count >= task.max_attempts:
            task.status = TaskStatus.dead_letter
            task.lease_token = None
            task.lease_expires_at = None
        else:
            task.status = TaskStatus.queued
            task.lease_token = None
            task.lease_expires_at = None
        self.session.flush()
        JobRepository(self.session).recompute_job_status(task.job_id)
        return task

    def heartbeat_lease(self, *, task_id: str, lease_token: str) -> tuple[bool, bool]:
        """续约 lease；返回 (ok, cancel_requested)。取消协作语义的探测点。"""
        task = self.get(task_id)
        if task.lease_token != lease_token:
            return False, False
        task.lease_expires_at = _utcnow() + timedelta(seconds=task.timeout_s or _LEASE_BASE_S)
        self.session.flush()
        # cancelling 流程在 C8 接入（cancel_requested 探测）；C2 阶段恒为 False
        return True, False


class ArtifactRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add_artifact(
        self,
        *,
        task_id: str,
        kind: str,
        uri: str,
        content_hash: str,
        metadata_json: dict | None = None,
    ) -> TaskArtifact:
        task = self.session.get(DurableTask, task_id)
        if task is None:
            raise NotFoundError(f"Task {task_id} not found")
        artifact = TaskArtifact(
            task_id=task_id,
            kind=kind,
            uri=uri,
            content_hash=content_hash,
            metadata_json=metadata_json or {},
        )
        self.session.add(artifact)
        self.session.flush()
        task.output_artifact_id = artifact.id
        self.session.flush()
        return artifact

    def list_for_task(self, task_id: str) -> list[TaskArtifact]:
        return list(
            self.session.execute(
                select(TaskArtifact)
                .where(TaskArtifact.task_id == task_id)
                .order_by(TaskArtifact.id)
            ).scalars()
        )
