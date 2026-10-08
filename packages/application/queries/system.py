"""系统状态查询（B6，设计② 观测面）"""

from __future__ import annotations


def get_system_status() -> dict:
    """库内规模 + 最近 pipeline 运行（worker 健康在 /system/worker，C7 并入 executor）"""
    from sqlalchemy import func, select

    from packages.storage.db import check_db_connection, session_scope
    from packages.storage.models import Paper, TopicSubscription
    from packages.storage.repositories import PipelineRunRepository

    db_ok = check_db_connection()
    with session_scope() as session:
        paper_count = session.execute(select(func.count()).select_from(Paper)).scalar() or 0
        embedded_count = (
            session.execute(
                select(func.count()).select_from(Paper).where(Paper.embedding.is_not(None))
            ).scalar()
            or 0
        )
        topic_count = (
            session.execute(select(func.count()).select_from(TopicSubscription)).scalar() or 0
        )
        runs = PipelineRunRepository(session).list_latest(limit=10)
        recent_runs = [
            {
                "pipeline": r.pipeline_name,
                "status": r.status.value if hasattr(r.status, "value") else str(r.status),
                "created_at": str(r.created_at) if r.created_at else None,
            }
            for r in runs[:5]
        ]
    return {
        "db_connected": db_ok,
        "paper_count": int(paper_count),
        "embedded_count": int(embedded_count),
        "topic_count": int(topic_count),
        "recent_runs_count": len(recent_runs),
        "recent_runs": recent_runs,
    }
