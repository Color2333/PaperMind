"""系统状态 & 指标路由
@author Color2333
"""

from fastapi import APIRouter, Query

from apps.api.deps import iso_dt, settings
from packages.storage.db import check_db_connection, session_scope
from packages.storage.repositories import (
    PaperRepository,
    PipelineRunRepository,
    PromptTraceRepository,
    TopicRepository,
)

router = APIRouter()


@router.get("/health")
def health() -> dict:
    db_ok = check_db_connection()
    status = "ok" if db_ok else "degraded"
    return {
        "status": status,
        "app": settings.app_name,
        "env": settings.app_env,
        "db": "connected" if db_ok else "unreachable",
    }


@router.get("/system/status")
def system_status() -> dict:
    with session_scope() as session:
        topics = TopicRepository(session).list_topics(enabled_only=False)
        papers = PaperRepository(session).list_latest(limit=200)
        runs = PipelineRunRepository(session).list_latest(limit=50)
        failed = [r for r in runs if r.status.value == "failed"]
        return {
            "health": health(),
            "counts": {
                "topics": len(topics),
                "enabled_topics": len([t for t in topics if t.enabled]),
                "papers_latest_200": len(papers),
                "runs_latest_50": len(runs),
                "failed_runs_latest_50": len(failed),
            },
            "latest_run": (
                {
                    "pipeline_name": runs[0].pipeline_name,
                    "status": runs[0].status.value,
                    "created_at": iso_dt(runs[0].created_at),
                    "error_message": runs[0].error_message,
                }
                if runs
                else None
            ),
        }


@router.get("/metrics/costs")
def cost_metrics(days: int = Query(default=7, ge=1, le=90)) -> dict:
    with session_scope() as session:
        return PromptTraceRepository(session).summarize_costs(days=days)
