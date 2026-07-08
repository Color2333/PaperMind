"""批量任务创建与状态查询。"""

from __future__ import annotations

import logging

from packages.ai.tools.types import ToolResult
from packages.storage.db import session_scope
from packages.storage.repositories import BatchJobRepository

logger = logging.getLogger(__name__)


def _create_batch_job(kind: str, paper_ids: list[str]) -> ToolResult:
    if not paper_ids:
        return ToolResult(success=False, summary="paper_ids 不能为空")
    try:
        with session_scope() as session:
            repo = BatchJobRepository(session)
            job = repo.create(kind=kind, paper_ids=paper_ids, created_by="agent")
            job_id = job.id
        label = {"skim": "粗读", "deep_read": "精读", "embed": "向量化"}.get(kind, kind)
        return ToolResult(
            success=True,
            data={"job_id": job_id, "kind": kind, "total": len(paper_ids)},
            summary=f"已提交批量{label}任务：{len(paper_ids)} 篇，job_id={job_id[:8]}...",
        )
    except Exception as exc:
        logger.exception("create batch job (%s) failed: %s", kind, exc)
        return ToolResult(success=False, summary=f"创建批量任务失败: {exc!s}")


def _batch_skim_papers(paper_ids: list[str]) -> ToolResult:
    return _create_batch_job("skim", paper_ids)


def _batch_deep_read_papers(paper_ids: list[str]) -> ToolResult:
    return _create_batch_job("deep_read", paper_ids)


def _batch_embed_papers(paper_ids: list[str]) -> ToolResult:
    return _create_batch_job("embed", paper_ids)


def _get_batch_job_status(job_id: str) -> ToolResult:
    try:
        with session_scope() as session:
            job = BatchJobRepository(session).get(job_id)
        if not job:
            return ToolResult(success=False, summary=f"批量任务 {job_id[:8]}... 不存在")
        label = {"skim": "粗读", "deep_read": "精读", "embed": "向量化"}.get(job.kind, job.kind)
        return ToolResult(
            success=True,
            data={
                "job_id": str(job.id),
                "kind": job.kind,
                "status": job.status,
                "total": job.total,
                "done": job.done,
                "failed": job.failed,
                "error_log": job.error_log,
            },
            summary=(
                f"批量{label}任务：{job.done}/{job.total} 完成"
                + (f"，{job.failed} 篇失败" if job.failed else "")
                + f"（状态: {job.status}）"
            ),
        )
    except Exception as exc:
        logger.exception("get_batch_job_status failed: %s", exc)
        return ToolResult(success=False, summary=f"查询任务状态失败: {exc!s}")
