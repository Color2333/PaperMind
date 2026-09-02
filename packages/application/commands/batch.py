"""批处理任务命令（B6 过渡；设计② StartBatchJob/GetJob）

现 `batch_jobs` 表 + API 进程 batch consumer 是 Stage C（C1/C11）的收敛对象；
本模块只把 agent 工具的创建/查询业务从 handler 下沉到 application，语义不变。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from packages.domain.exceptions import NotFoundError

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def create_batch_job(
    session: Session, *, kind: str, paper_ids: list[str], created_by: str = "agent"
) -> dict[str, Any]:
    """创建批量任务（skim/deep_read/embed）；C11 起转 durable Job"""
    from packages.storage.repositories import BatchJobRepository

    job = BatchJobRepository(session).create(kind=kind, paper_ids=paper_ids, created_by=created_by)
    return {"job_id": job.id, "kind": job.kind, "total": len(paper_ids)}


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
