"""任务观测查询（C3 退出口：durable store 是唯一状态源）

旧内存任务追踪器（B5 过渡的 600s TTL 内存态）已整体删除。
`/tasks/{id}` 统一视图解析顺序：durable Task id 直接命中 → external_ref
（历史行的过渡引用）。任务提交入口返回的 task_id 即 durable Task id。
"""

from __future__ import annotations

from datetime import UTC
from typing import Any

_STATUS_MAP = {
    "queued": "pending",
    "leased": "running",
    "running": "running",
    "succeeded": "completed",
    "failed": "failed",
    "dead_letter": "failed",
    "manual_recovery": "failed",
    "cancelled": "cancelled",
}
_FINISHED = ("succeeded", "failed", "dead_letter", "cancelled")


def _unified_view(task, session) -> dict[str, Any]:  # noqa: ANN001
    """durable Task → 旧 /tasks/{id} 轮询形状（前端契约保持）"""
    from packages.storage.models import Job

    job = session.get(Job, task.job_id)
    progress = (job.progress or {}) if job else {}
    status_value = task.status.value if hasattr(task.status, "value") else str(task.status)
    finished = status_value in _FINISHED
    total = progress.get("total") or 100
    current = progress.get("current", total if finished else 0)
    return {
        "task_id": task.id,
        "task_type": (job.kind.lower() if job else "durable"),
        "category": "durable",
        "title": progress.get("message", ""),
        "current": current,
        "total": total,
        "message": progress.get("message", ""),
        "progress": (current / total) if total else 0,
        "finished": finished,
        "success": status_value == "succeeded",
        "status": _STATUS_MAP.get(status_value, "running"),
        "error": task.last_error,
        "has_result": bool((task.input_ref or {}).get("result_ref")),
        "job_id": job.id if job else None,
        "durable": True,
    }


def _find_durable_task(session, task_ref: str):  # noqa: ANN202
    """durable Task id 直查优先；未命中回退 external_ref（历史过渡引用）"""
    from packages.storage.models import DurableTask
    from packages.storage.repositories import TaskRepository

    task = session.get(DurableTask, task_ref)
    if task is not None:
        return task
    return TaskRepository(session).get_by_external_ref(task_ref)


def resolve_task_unified(session, task_ref: str) -> dict[str, Any] | None:
    """统一任务视图（/tasks/{id} 轮询形状）；未命中返回 None"""
    task = _find_durable_task(session, task_ref)
    if task is None:
        return None
    return _unified_view(task, session)


def get_task_status(task_id: str) -> dict[str, Any] | None:
    """返回 {"task": 统一视图, "result": 已完成结果}；不存在返回 None"""
    from packages.storage.db import session_scope

    with session_scope() as session:
        view = resolve_task_unified(session, task_id)
        if view is None:
            return None
        result = None
        if view["success"]:
            result = _result_of(session, task_id)
        return {"task": view, "result": result}


def get_task_info(task_id: str) -> dict | None:
    """平铺的统一视图（/ingest/references/status 等旧形状消费方）"""
    from packages.storage.db import session_scope

    with session_scope() as session:
        return resolve_task_unified(session, task_id)


def list_active_tasks() -> list[dict]:
    """在途任务（queued/leased/running）——durable store 唯一来源"""
    from sqlalchemy import select

    from packages.storage.db import session_scope
    from packages.storage.models import DurableTask

    with session_scope() as session:
        rows = session.execute(
            select(DurableTask).where(DurableTask.status.in_(["queued", "leased", "running"]))
        ).scalars()
        return [_unified_view(t, session) for t in rows]


def _result_of(session, task_ref: str) -> dict | None:  # noqa: ANN001
    task = _find_durable_task(session, task_ref)
    if task is None or (task.status.value if hasattr(task.status, "value") else "") != "succeeded":
        return None
    return (task.input_ref or {}).get("result_ref") or {}


def get_task_result(task_id: str) -> dict | None:
    """已完成任务的结果摘要；未完成/不存在返回 None"""
    from packages.storage.db import session_scope

    with session_scope() as session:
        return _result_of(session, task_id)


def find_fetch_task_by_topic(topic_id: str) -> dict | None:
    """按主题匹配在途的订阅抓取任务（StartTopicResearch）"""
    from sqlalchemy import select

    from packages.storage.db import session_scope
    from packages.storage.models import DurableTask

    with session_scope() as session:
        rows = session.execute(
            select(DurableTask).where(
                DurableTask.capability == "fetch_topic_papers",
                DurableTask.status.in_(["queued", "leased", "running"]),
            )
        ).scalars()
        for t in rows:
            if topic_id[:8] in str((t.input_ref or {}).get("topic_id", "")):
                return _unified_view(t, session)
    return None


def list_pipeline_runs(*, limit: int = 30) -> dict:
    """最近 pipeline 运行记录（过渡观测；Stage C 后并入 Job/Attempt）"""
    from packages.storage.db import session_scope
    from packages.storage.repositories import PipelineRunRepository

    with session_scope() as session:
        runs = PipelineRunRepository(session).list_latest(limit=limit)
        return {
            "items": [
                {
                    "id": r.id,
                    "pipeline_name": r.pipeline_name,
                    "paper_id": r.paper_id,
                    "status": r.status.value,
                    "decision_note": r.decision_note,
                    "elapsed_ms": r.elapsed_ms,
                    "error_message": r.error_message,
                    "created_at": _iso_dt(r.created_at),
                }
                for r in runs
            ]
        }


def _iso_dt(dt):
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()
