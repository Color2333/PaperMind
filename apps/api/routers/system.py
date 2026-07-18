"""系统状态 & 指标路由
@author Color2333
"""

import time
from pathlib import Path

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

# worker 心跳文件（pm_data 共享卷，worker 写、backend 读）
_WORKER_HEARTBEAT_FILE = Path("/app/data/worker_heartbeat.json")
_HEARTBEAT_STALE_SECONDS = 1200  # 与 worker healthcheck 一致


def _read_worker_heartbeat() -> dict:
    """读共享卷 worker 心跳，返回 {ts, error, age_seconds, is_stale}；文件缺失返回 None。"""
    import json

    try:
        data = json.loads(_WORKER_HEARTBEAT_FILE.read_text())
        ts = float(data.get("ts", 0))
        age = time.time() - ts
        return {
            "ts": ts,
            "error": data.get("error"),
            "age_seconds": int(age),
            "is_stale": age > _HEARTBEAT_STALE_SECONDS,
        }
    except (OSError, ValueError, TypeError):
        return None


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


@router.get("/system/worker")
def worker_status() -> dict:
    """Worker 心跳状态（可观测性：供 Operations 面板 + 告警自检查询）"""
    hb = _read_worker_heartbeat()
    return {
        "heartbeat": hb,
        "stale_threshold": _HEARTBEAT_STALE_SECONDS,
    }


@router.get("/system/status")
def system_status() -> dict:
    with session_scope() as session:
        topics = TopicRepository(session).list_topics(enabled_only=False)
        # 浪费的全量加载修复：此前拉 200 行 ORM 仅为 len()，改 count_all() 一次 COUNT 查询
        papers_total = PaperRepository(session).count_all()
        runs = PipelineRunRepository(session).list_latest(limit=50)
        failed = [r for r in runs if r.status.value == "failed"]
        # 可观测性：附带 worker 心跳摘要 + 主题抓取错误计数
        errored_topics = [t for t in topics if t.last_error]
        return {
            "health": health(),
            "counts": {
                "topics": len(topics),
                "enabled_topics": len([t for t in topics if t.enabled]),
                "papers_latest_200": papers_total,
                "runs_latest_50": len(runs),
                "failed_runs_latest_50": len(failed),
            },
            "worker_heartbeat": _read_worker_heartbeat(),
            "topic_errors": len(errored_topics),
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
def cost_metrics(days: int = Query(default=7, ge=0, le=3650)) -> dict:
    with session_scope() as session:
        return PromptTraceRepository(session).summarize_costs(days=days)
