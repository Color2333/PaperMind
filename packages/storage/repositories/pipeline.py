"""
流水线运行数据仓储
@author Color2333
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.orm import Session

from packages.domain.enums import PipelineStatus
from packages.storage.models import PipelineRun


class PipelineRunRepository:
    def __init__(self, session: Session):
        self.session = session

    def start(
        self,
        pipeline_name: str,
        paper_id: UUID | None = None,
        decision_note: str | None = None,
    ) -> PipelineRun:
        run = PipelineRun(
            pipeline_name=pipeline_name,
            paper_id=str(paper_id) if paper_id else None,
            status=PipelineStatus.running,
            decision_note=decision_note,
        )
        self.session.add(run)
        self.session.flush()
        return run

    def finish(self, run_id: UUID, elapsed_ms: int | None = None) -> None:
        run = self.session.get(PipelineRun, str(run_id))
        if not run:
            return
        run.status = PipelineStatus.succeeded
        run.elapsed_ms = elapsed_ms

    def fail(self, run_id: UUID, error_message: str) -> None:
        run = self.session.get(PipelineRun, str(run_id))
        if not run:
            return
        run.status = PipelineStatus.failed
        run.retry_count += 1
        run.error_message = error_message

    def list_latest(self, limit: int = 30) -> list[PipelineRun]:
        q = select(PipelineRun).order_by(PipelineRun.created_at.desc()).limit(limit)
        return list(self.session.execute(q).scalars())
