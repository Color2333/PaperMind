"""旧任务观测查询（B5 过渡；Stage C 后并入 GetJob/ListJobs）

包装内存 `global_tracker`（审计 §2.1：600s TTL、重启即丢）——C3 的收敛对象。
此处只做读取包装，不新增任务状态语义。
"""

from __future__ import annotations

from typing import Any

from packages.domain.task_tracker import global_tracker


def get_task_status(task_id: str) -> dict[str, Any] | None:
    """返回 {"task": to_dict, "result": fn 返回值}；不存在/过期返回 None"""
    info = global_tracker.get_task(task_id)
    if info is None:
        return None
    return {"task": info, "result": global_tracker.get_result(task_id)}


def get_task_info(task_id: str) -> dict | None:
    """平铺的 to_dict（/ingest/references/status 等旧形状消费方）"""
    return global_tracker.get_task(task_id)


def list_active_tasks() -> list[dict]:
    return global_tracker.get_active()


def get_task_result(task_id: str) -> Any | None:
    """已完成任务的 fn 返回值；任务不存在返回 None"""
    return global_tracker.get_result(task_id)


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


def find_fetch_task_by_topic(topic_id: str) -> dict | None:
    """过渡：按主题短前缀在 tracker 中找匹配的手动抓取任务（C10 后并入 GetJob）"""
    active = global_tracker.get_active()
    for t in active:
        if t["task_type"] == "fetch" and topic_id[:8] in t.get("task_id", ""):
            return t
    return None


def _iso_dt(dt):
    from datetime import UTC

    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()
