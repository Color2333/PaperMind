"""批处理任务命令（C13 退出口修订：durable ProcessUnreadBatch 是唯一权威）

第三轮 REVIEW：新请求直接创建 durable Job 并返回 durable job id——
不再双写 batch_jobs 表。batch_jobs 降级为只读历史迁移层：
- BatchJobRepository.create 仅允许显式 migrate=True 的迁移脚本调用；
- get_batch_job 支持两种 id：durable job id（新）与历史 batch_jobs 行 id（旧）。
删除日期：待 agent 工具的 batch id 全部切换为 durable id 后（I1 退出门）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from packages.domain.exceptions import NotFoundError

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def create_batch_job(
    session: Session, *, kind: str, paper_ids: list[str], created_by: str = "agent"
) -> dict[str, Any]:
    """创建批量任务（skim/deep_read/embed）——直接创建 durable ProcessUnreadBatch。

    返回的 job_id 即 durable Job id（不再双写 batch_jobs 行）。
    """
    from packages.application.commands.workflows import expand_job, start_workflow_job

    capability = f"{kind}_paper" if kind in ("skim", "deep_read") else "embed_paper"
    workflow_job, _wf_tasks, _created = start_workflow_job(
        session,
        kind="ProcessUnreadBatch",
        payload={"paper_ids": paper_ids, "kinds": [capability]},
        created_by=created_by,
    )
    expand_job(session, workflow_job.id)
    return {
        "job_id": workflow_job.id,
        "kind": kind,
        "total": len(paper_ids),
        "durable_job_id": workflow_job.id,
    }


def get_batch_job(session: Session, job_id: str) -> dict[str, Any] | None:
    """查询批量任务状态。

    job_id 语义（向后兼容）：
    - durable Job id（新路径返回的）→ 直接投影 Job graph；
    - 历史 batch_jobs 行 id → 只读迁移投影（经 idempotency_key=batch:{id} 关联；
      无 durable Job 的历史行返回冻结值）。
    """
    from packages.application.queries.jobs import get_job_graph
    from packages.storage.models import Job
    from packages.storage.repositories import BatchJobRepository

    # 新语义：durable Job id 直查
    durable_job = session.get(Job, job_id)
    if durable_job is None:
        # 旧语义：历史 batch_jobs 行经幂等键关联
        legacy = None
        try:
            legacy = BatchJobRepository(session).get(job_id)
        except (ValueError, NotFoundError):
            return None
        if legacy is None:
            return None
        durable_job = session.execute(
            select(Job).where(Job.idempotency_key == f"batch:{job_id}")
        ).scalar_one_or_none()

    if durable_job is None:
        return None
    graph = get_job_graph(session, durable_job.id)
    tasks = graph["tasks"]
    done = sum(1 for t in tasks if t["status"] == "succeeded")
    failed = sum(1 for t in tasks if t["status"] in ("failed", "dead_letter"))
    errors = [t["last_error"] for t in tasks if t.get("last_error")]
    return {
        "job_id": str(durable_job.id),
        "kind": durable_job.payload.get("kind", "batch"),
        "status": graph["status"],
        "total": len(tasks),
        "done": done,
        "failed": failed,
        "error_log": errors,
        "durable_job_id": durable_job.id,
    }


def get_batch_job_legacy_row(session: Session, legacy_id: str) -> dict[str, Any] | None:
    """历史 batch_jobs 行的只读投影（迁移适配器；新代码禁止创建行）"""
    from packages.storage.repositories import BatchJobRepository

    try:
        job = BatchJobRepository(session).get(legacy_id)
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
