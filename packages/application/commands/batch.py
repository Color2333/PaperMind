"""批处理任务命令（C11：batch_jobs 保留兼容，durable ProcessUnreadBatch 为权威记录）"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from packages.domain.exceptions import NotFoundError

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def create_batch_job(
    session: Session, *, kind: str, paper_ids: list[str], created_by: str = "agent"
) -> dict[str, Any]:
    """创建批量任务（skim/deep_read/embed）。

    C11：同时创建 durable ProcessUnreadBatch Job（幂等键含 batch_job id），
    旧 batch_jobs 行保留兼容（worker consumer 渐进迁移到 C11 完成）。
    """
    from packages.application.commands.workflows import expand_job, start_workflow_job
    from packages.storage.repositories import BatchJobRepository

    job = BatchJobRepository(session).create(kind=kind, paper_ids=paper_ids, created_by=created_by)
    # batch kind → capability 名（注册表；"skim"→"skim_paper"、"deep_read"→"deep_read_paper"）
    capability = f"{kind}_paper" if kind in ("skim", "deep_read") else "embed_paper"
    workflow_job, _wf_tasks, _wf_created = start_workflow_job(
        session,
        kind="ProcessUnreadBatch",
        payload={"paper_ids": paper_ids, "kinds": [capability], "batch_job_id": job.id},
        idempotency_key=f"batch:{job.id}",
        created_by=created_by,
    )
    expand_job(session, workflow_job.id)
    return {
        "job_id": job.id,
        "kind": kind,
        "total": len(paper_ids),
        "durable_job_id": workflow_job.id,
    }


def get_batch_job(session: Session, job_id: str) -> dict[str, Any] | None:
    """查询批量任务状态；不存在返回 None"""
    from packages.storage.repositories import BatchJobRepository

    try:
        job = BatchJobRepository(session).get(job_id)
    except (ValueError, NotFoundError):
        return None
    if job is None:
        return None
    return {
        "job_id": str(job.id),
        "kind": job.kind,
        "status": job.status,
        "total": job.total,
        "done": job.done,
        "failed": job.failed,
        "error_log": job.error_log,
    }
