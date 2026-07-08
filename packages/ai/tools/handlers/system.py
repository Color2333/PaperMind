"""系统状态查询。"""

from __future__ import annotations

import logging

from packages.ai.tools.types import ToolResult
from packages.storage.db import check_db_connection, session_scope
from packages.storage.repositories import PipelineRunRepository

logger = logging.getLogger(__name__)


def _get_system_status() -> ToolResult:
    try:
        from sqlalchemy import func
        from sqlalchemy import select as sa_select

        from packages.storage.models import Paper, TopicSubscription

        db_ok = check_db_connection()
        with session_scope() as session:
            paper_count = session.execute(sa_select(func.count()).select_from(Paper)).scalar() or 0
            embedded_count = (
                session.execute(
                    sa_select(func.count()).select_from(Paper).where(Paper.embedding.is_not(None))
                ).scalar()
                or 0
            )
            topic_count = (
                session.execute(sa_select(func.count()).select_from(TopicSubscription)).scalar()
                or 0
            )
            run_repo = PipelineRunRepository(session)
            runs = run_repo.list_latest(limit=10)
            recent_runs = [
                {
                    "pipeline": r.pipeline_name,
                    "status": r.status.value if hasattr(r.status, "value") else str(r.status),
                    "created_at": str(r.created_at) if r.created_at else None,
                }
                for r in runs[:5]
            ]
        return ToolResult(
            success=True,
            data={
                "db_connected": db_ok,
                "paper_count": paper_count,
                "embedded_count": embedded_count,
                "topic_count": topic_count,
                "recent_runs_count": len(recent_runs),
                "recent_runs": recent_runs,
            },
            summary=(
                f"论文 {paper_count} 篇（{embedded_count} 已向量化），"
                f"主题 {topic_count} 个" + ("" if db_ok else " ⚠️数据库异常")
            ),
        )
    except Exception as exc:
        logger.exception("get_system_status failed: %s", exc)
        return ToolResult(success=False, summary=f"获取系统状态失败: {exc!s}")
