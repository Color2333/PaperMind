"""Job 只读查询（C3，设计③：Job graph 统一观察面）"""

from __future__ import annotations

from datetime import UTC
from typing import TYPE_CHECKING

from packages.storage.repositories import JobRepository, TaskRepository

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def _iso(dt) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()


def list_jobs(
    session: Session, *, status: str | None = None, kind: str | None = None, limit: int = 50
) -> dict:
    from sqlalchemy import select

    from packages.storage.models import Job

    q = select(Job).order_by(Job.created_at.desc()).limit(limit)
    if status:
        q = q.where(Job.status == status)
    if kind:
        q = q.where(Job.kind == kind)
    jobs = list(session.execute(q).scalars())
    return {
        "items": [
            {
                "id": j.id,
                "kind": j.kind,
                "status": j.status.value if hasattr(j.status, "value") else str(j.status),
                "priority": j.priority,
                "progress": j.progress or {},
                "created_by": j.created_by,
                "research_run_id": j.research_run_id,
                "created_at": _iso(j.created_at),
                "started_at": _iso(j.started_at),
                "finished_at": _iso(j.finished_at),
            }
            for j in jobs
        ]
    }


def get_job_graph(session: Session, job_id: str) -> dict:
    """Job + 子 Task graph（设计③ §5.3：观察面统一入口）"""
    job = JobRepository(session).get(job_id)
    tasks = TaskRepository(session).list_for_job(job_id)
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status.value if hasattr(job.status, "value") else str(job.status),
        "payload": job.payload or {},
        "priority": job.priority,
        "budget": job.budget or {},
        "progress": job.progress or {},
        "research_run_id": job.research_run_id,
        "created_by": job.created_by,
        "created_at": _iso(job.created_at),
        "started_at": _iso(job.started_at),
        "finished_at": _iso(job.finished_at),
        "tasks": [
            {
                "id": t.id,
                "seq": t.seq,
                "capability": t.capability,
                "handler_version": t.handler_version,
                "status": t.status.value if hasattr(t.status, "value") else str(t.status),
                "attempt_count": t.attempt_count,
                "resource_class": t.resource_class,
                "timeout_s": t.timeout_s,
                "max_attempts": t.max_attempts,
                "lease_expires_at": _iso(t.lease_expires_at),
                "last_error": t.last_error,
                "external_ref": t.external_ref,
                "output_artifact_id": t.output_artifact_id,
            }
            for t in tasks
        ],
    }


def get_job_attempts(session, job_id: str) -> list[dict]:
    """Job 下全部 Attempt（观察面：错误/成本溯源）"""
    from sqlalchemy import select

    from packages.storage.models import DurableTask, TaskAttempt

    rows = session.execute(
        select(TaskAttempt)
        .join(DurableTask, TaskAttempt.task_id == DurableTask.id)
        .where(DurableTask.job_id == job_id)
        .order_by(TaskAttempt.id)
    ).scalars()
    return [
        {
            "id": a.id,
            "task_id": a.task_id,
            "attempt_no": a.attempt_no,
            "executor_id": a.executor_id,
            "fencing_token": a.fencing_token,
            "status": a.status.value if hasattr(a.status, "value") else str(a.status),
            "error_class": a.error_class,
            "error_message": a.error_message,
            "started_at": _iso(a.started_at),
            "finished_at": _iso(a.finished_at),
        }
        for a in rows
    ]
