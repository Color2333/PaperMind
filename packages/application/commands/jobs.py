"""统一任务提交（C3 退出口：权威入口 submit_job，旧 tracker 桥接已退役）

- `submit_job` 只写 durable Job/Task（queued），执行由独立 Python Executor
  经 Go Core 调度（claim→handler→fencing 提交）——API/命令不得在此启动
  线程或 fn（设计③「API 只负责提交、查询和控制」）；
- 观察面（/jobs、/tasks/*）直接读 durable store；
- cancel/retry/pause/resume 为控制面命令，pause 持久化到 system_flags。
"""

from __future__ import annotations

from typing import Any


def submit_job(
    *,
    kind: str,
    capability: str,
    title: str = "",
    payload: dict | None = None,
    input_ref: dict | None = None,
    idempotency_key: str | None = None,
    resource_class: str = "default",
    timeout_s: int = 1800,
    max_attempts: int = 1,
    priority: int = 0,
    research_run_id: str | None = None,
    created_by: str = "api",
) -> dict:
    """权威提交入口：只写 durable Job/Task（queued），不 claim、不执行。

    执行由独立 Python Executor 经 Go Core 调度（领取→handler→fencing 提交）。
    调用方（API/CLI/agent）不得在此启动线程或 fn——见设计③「API 只负责提交、
    查询和控制」。input_ref 是 handler 的输入契约（见 C4 注册表 input_keys）。
    """
    from packages.storage.db import session_scope
    from packages.storage.repositories import JobRepository, TaskRepository

    with session_scope() as session:
        job_repo = JobRepository(session)
        task_repo = TaskRepository(session)
        job, _created = job_repo.create_job(
            kind=kind,
            payload={**(payload or {}), "title": title} if title else (payload or {}),
            idempotency_key=idempotency_key,
            priority=priority,
            research_run_id=research_run_id,
            created_by=created_by,
        )
        task, task_created = task_repo.add_task(
            job_id=job.id,
            capability=capability,
            input_ref=input_ref or {},
            idempotency_key=(f"{idempotency_key}:task:0" if idempotency_key else None),
            seq=0,
            priority=priority,
            resource_class=resource_class,
            timeout_s=timeout_s,
            max_attempts=max_attempts,
        )
        job_id, task_id = job.id, task.id
        task_status = task.status.value if hasattr(task.status, "value") else str(task.status)

    return {
        "job_id": job_id,
        "task_id": task_id,
        "capability": capability,
        "status": task_status,
        "created": task_created,
    }


def cancel_job(job_id: str) -> dict[str, int]:
    """取消 Job：未领取 Task 直接取消，运行中的协作取消"""
    from packages.storage.db import session_scope
    from packages.storage.repositories import TaskRepository

    with session_scope() as session:
        return TaskRepository(session).cancel_job(job_id)


def retry_job(job_id: str) -> dict[str, Any]:
    """重试 Job：dead_letter/failed Task 重回队列"""
    from packages.storage.db import session_scope
    from packages.storage.repositories import TaskRepository

    with session_scope() as session:
        retried = TaskRepository(session).retry_job(job_id)
        return {"job_id": job_id, "retried": retried}


def retry_task(task_id: str) -> dict[str, Any]:
    """单 Task 重试（dead_letter 出口）"""
    from packages.storage.db import session_scope
    from packages.storage.repositories import TaskRepository

    with session_scope() as session:
        task = TaskRepository(session).retry_task(task_id)
    return {
        "task_id": task_id,
        "status": task.status.value if hasattr(task.status, "value") else str(task.status),
    }


def pause_queue() -> dict[str, Any]:
    """暂停队列（持久化到 system_flags——跨进程生效，executor 侧 claim 同样可见）"""
    from packages.storage.db import session_scope
    from packages.storage.repositories import durable as durable_repo

    with session_scope() as session:
        durable_repo.pause_queue(session)
    return {"paused": True}


def resume_queue() -> dict[str, Any]:
    from packages.storage.db import session_scope
    from packages.storage.repositories import durable as durable_repo

    with session_scope() as session:
        durable_repo.resume_queue(session)
    return {"paused": False}
