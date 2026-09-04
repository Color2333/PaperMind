"""统一任务提交（C3 退出口 + Go-authority 切片路由）

- `submit_job` 只写 Job/Task（queued），执行由独立 Python Executor 经 Go Core
  调度——API/命令不得在此启动线程或 fn（设计③「API 只负责提交、查询和控制」）；
- **Go-authority 切片**（第三轮 P0-2 选 a）：`skim_paper` 路由到 Go Core 的
  权威 Job/Task/Attempt 存储（PAPERMIND_CORE_URL）；其余 capability 暂留
  Python durable store（逐 capability 迁移，迁移清单见路线图 C6）；
- 观察面（/jobs、/tasks/*）合并两权威（durable store + Go proxy）；
- cancel/retry/pause/resume 为控制面命令，pause 持久化到 system_flags。
"""

from __future__ import annotations

from typing import Any

# 已迁移到 Go 权威的 capability（切片：skim → deep_read → embed；逐项迁移中）
# A 档 capability（Go apply-result SQL 直写）；其余为 B 档（Go 落终态，领域 apply 留 Python）
A_TIER_CAPABILITIES = {"skim_paper", "deep_read_paper", "embed_paper", "extract_claims"}


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
    # Go-authority 全量路由：配置了 PAPERMIND_CORE_URL → 所有 capability 提交
    # Go 权威（调度/fencing/终态）。领域 apply 按 A/B 档分派（设计④ §2.3）。
    # 未配置 = 本地单进程模式（全 Python durable store）。
    if _core_api_enabled():
        return _submit_via_go_core(
            kind=kind,
            capability=capability,
            title=title,
            input_ref=input_ref or {},
            idempotency_key=idempotency_key,
            timeout_s=timeout_s,
        )

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


def _core_api_enabled() -> bool:
    """是否启用 Go-authority 路由（部署开关：PAPERMIND_CORE_URL）"""
    import os

    return bool(os.environ.get("PAPERMIND_CORE_URL"))


def _submit_via_go_core(
    *,
    kind: str,
    capability: str,
    title: str,
    input_ref: dict,
    idempotency_key: str | None,
    timeout_s: int = 1800,
) -> dict:
    """经 Go Core 提交（权威 Job/Task/Attempt 在 Go）。Core 不可达 → 抛错（fail closed）。"""
    import os

    from packages.core_client.client import CoreClient

    base = os.environ["PAPERMIND_CORE_URL"]
    token = os.environ.get("PAPERMIND_CORE_TOKEN", "")
    client = CoreClient(base, token=token, timeout_s=10.0)
    try:
        body = client.submit_job(
            kind=kind,
            capability=capability,
            input_ref=input_ref,
            idempotency_key=idempotency_key,
            timeout_s=timeout_s,
        )
    finally:
        client.close()
    return {
        "job_id": body["job_id"],
        "task_id": body["task_id"],
        "capability": capability,
        "status": body.get("status", "queued"),
        "created": bool(body.get("created", True)),
        "authority": "go_core",
    }


def get_go_job_graph(job_id: str) -> dict | None:
    """从 Go 权威读 Job graph（观察面代理；非 Go 任务/未配置返回 None）"""
    import os

    if not os.environ.get("PAPERMIND_CORE_URL"):
        return None
    from packages.core_client.client import CoreClient

    client = CoreClient(
        os.environ["PAPERMIND_CORE_URL"], token=os.environ.get("PAPERMIND_CORE_TOKEN", "")
    )
    try:
        return client.jobs_graph(job_id)
    finally:
        client.close()


def list_go_jobs(limit: int = 20) -> list[dict]:
    """Go 权威 Job 列表（观察面合并；未配置返回 []）"""
    import os

    if not os.environ.get("PAPERMIND_CORE_URL"):
        return []
    from packages.core_client.client import CoreClient

    client = CoreClient(
        os.environ["PAPERMIND_CORE_URL"], token=os.environ.get("PAPERMIND_CORE_TOKEN", "")
    )
    try:
        return client.jobs_list(limit)
    finally:
        client.close()


def cancel_job(job_id: str) -> dict[str, int]:
    """取消 Job：Go 权威 job 代理取消；其余 python durable 取消"""
    from packages.storage.db import session_scope
    from packages.storage.repositories import TaskRepository

    # Go 权威优先（skim/deep_read/embed 切片）
    if _core_api_enabled():
        from packages.core_client.client import CoreClient

        client = CoreClient(
            __import__("os").environ["PAPERMIND_CORE_URL"],
            token=__import__("os").environ.get("PAPERMIND_CORE_TOKEN", ""),
        )
        try:
            body = client._call(f"/v1/jobs/{job_id}/cancel", {})
            return {"cancelled": 0, "cancel_requested": 0, "go": body.get("counts", {})}
        except Exception:
            pass  # 非 Go job / core 不可达 → 回退 python durable
        finally:
            client.close()

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
