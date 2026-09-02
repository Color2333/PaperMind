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


def list_active_tasks() -> list[dict]:
    return global_tracker.get_active()
