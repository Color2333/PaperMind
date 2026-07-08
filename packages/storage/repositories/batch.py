"""
批量任务数据仓储
@author Color2333
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from packages.storage.models import BatchJob

from ._base import BaseQuery


class BatchJobRepository(BaseQuery):
    def create(self, kind: str, paper_ids: list[str], created_by: str = "agent") -> BatchJob:
        job = BatchJob(
            kind=kind,
            paper_ids=paper_ids,
            total=len(paper_ids),
            created_by=created_by,
        )
        self.session.add(job)
        self.session.flush()
        return job

    def get(self, job_id: str) -> BatchJob | None:
        return self.session.get(BatchJob, job_id)

    def claim_next(self) -> BatchJob | None:
        """原子拿一条 pending 改成 running"""
        job = self.session.execute(
            select(BatchJob)
            .where(BatchJob.status == "pending")
            .order_by(BatchJob.created_at.asc())
            .limit(1)
            .with_for_update(skip_locked=True)
        ).scalar_one_or_none()
        if job:
            job.status = "running"
            job.started_at = datetime.now(UTC)
            self.session.flush()
        return job

    def mark_progress(
        self,
        job_id: str,
        done_delta: int = 0,
        failed_delta: int = 0,
        error_patch: dict | None = None,
    ) -> None:
        job = self.get(job_id)
        if not job:
            return
        job.done = (job.done or 0) + done_delta
        job.failed = (job.failed or 0) + failed_delta
        if error_patch:
            log = dict(job.error_log or {})
            log.update(error_patch)
            job.error_log = log
        self.session.flush()

    def mark_finished(self, job_id: str, status: str) -> None:
        job = self.get(job_id)
        if not job:
            return
        job.status = status
        job.finished_at = datetime.now(UTC)
        self.session.flush()

    def recover_stale_running(self) -> int:
        """启动时把 running 状态的恢复成 failed（幂等）"""
        stale = list(
            self.session.execute(select(BatchJob).where(BatchJob.status == "running")).scalars()
        )
        for job in stale:
            job.status = "failed"
            job.finished_at = datetime.now(UTC)
        self.session.flush()
        return len(stale)
