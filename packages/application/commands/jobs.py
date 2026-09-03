"""统一任务提交桥接（C3，设计③ §6 迁移说明）

`submit_durable_job` 把「tracker.submit + 内存进度」的旧入口升级为
**durable Job + Task + Attempt 持久化**：

- Job/Task 先落库（queued），随后 claim（leased + lease + attempt）——
  durable store 从此是任务状态的权威记录，tracker 只是在进程内驱动 fn 的执行通道；
- fn 的 progress 回调双写：透传给 tracker（前端兼容）+ 刷新 durable 进度/lease；
- fn 成功 → complete_task（result 摘要存 Task）；异常 → fail_task（按 max_attempts
  决定重试/dead_letter，C2 语义）→ recompute 收敛 Job；
- fn 内部可用 `context.progress(msg, cur, tot)` 上报；进度同时续约 lease，
  防长任务租期过期。

C7 起 fn 由 Python Executor 经 Go Core 协议执行，本桥接的任务提交面不变。
"""

from __future__ import annotations

import logging
from contextlib import suppress
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


def submit_durable_job(
    *,
    kind: str,
    capability: str,
    title: str,
    fn: Callable[..., Any],
    payload: dict | None = None,
    idempotency_key: str | None = None,
    resource_class: str = "default",
    timeout_s: int = 1800,
    max_attempts: int = 1,
    research_run_id: str | None = None,
    created_by: str = "api",
    category: str = "analysis",
    total: int = 100,
    fn_kwargs: dict | None = None,
) -> dict:
    """创建 durable Job/Task 并经 tracker 驱动执行；返回 {"task_id","job_id","status"}。

    fn 签名：fn(progress_callback: Callable[[str,int,int],None] | None = None, **fn_kwargs) -> Any
    （JSON-able 返回值会存入 Task result，供 /tasks/{id}/result 查询。）
    """
    from packages.domain.task_tracker import global_tracker
    from packages.storage.db import session_scope
    from packages.storage.repositories import JobRepository, TaskRepository

    # 1. 落库 Job + Task（queued）→ claim（leased + lease + attempt）→ Job running
    with session_scope() as session:
        job_repo = JobRepository(session)
        task_repo = TaskRepository(session)
        job, _created = job_repo.create_job(
            kind=kind,
            payload=payload or {},
            idempotency_key=idempotency_key,
            research_run_id=research_run_id,
            created_by=created_by,
        )
        job_id = job.id
        task, _task_created = task_repo.add_task(
            job_id=job_id,
            capability=capability,
            idempotency_key=(f"{idempotency_key}:task:0" if idempotency_key else None),
            resource_class=resource_class,
            timeout_s=timeout_s,
            max_attempts=max_attempts,
            external_ref=f"pending:{new_ref_id()}",
        )
        task_id = task.id
        # fn 与 Task 绑定——按 ID 领取（签发 lease + attempt + fencing）
        claimed = task_repo.claim_task_by_id(task_id=task_id, executor_id="api-thread")
        lease_token = claimed.lease_token

    # 2. 进度桥接：透传 tracker + 刷新 durable 进度/lease
    progress_state = {"current": 0, "total": total}

    def _bridged_progress(msg: str, cur: int, tot: int) -> None:
        progress_state["current"], progress_state["total"] = cur, tot
        with suppress(Exception), session_scope() as session:
            JobRepository(session).update_progress(job_id, current=cur, total=tot, message=msg)
            TaskRepository(session).touch_lease(task_id, lease_token)

    # 3. fn 包装：成功/失败写回 durable，并转发 tracker 的原始进度协议
    def _wrapped(progress_callback=None):
        def _dual(msg, cur, tot):
            if progress_callback:
                progress_callback(msg, cur, tot)
            _bridged_progress(msg, cur, tot)

        try:
            result = fn(progress_callback=_dual, **(fn_kwargs or {}))
        except Exception as exc:
            logger.exception("durable job %s task %s failed: %s", job_id, task_id, exc)
            with session_scope() as session:
                TaskRepository(session).fail_task(
                    task_id=task_id,
                    executor_id="api-thread",
                    lease_token=lease_token,
                    error_class=type(exc).__name__,
                    message=str(exc),
                )
            raise
        # tracker 通道返回 JSON-able 结果（与旧 model_dump() 行为一致）
        json_result = _jsonable(result)
        with suppress(Exception), session_scope() as session:
            TaskRepository(session).complete_task(
                task_id=task_id,
                executor_id="api-thread",
                lease_token=lease_token,
                result_ref=json_result,
            )
        return json_result

    # 4. tracker 驱动执行（进程内通道；C7 换 Executor），回填 external_ref
    tracker_task_id = global_tracker.submit(
        task_type=kind.lower(),
        title=title,
        fn=_wrapped,
        total=total,
        category=category,
    )
    with suppress(Exception), session_scope() as session:
        TaskRepository(session).set_external_ref(task_id, tracker_task_id)

    return {
        "task_id": tracker_task_id,
        "job_id": job_id,
        "durable_task_id": task_id,
        "status": "running",
    }


def new_ref_id() -> str:
    from uuid import uuid4

    return uuid4().hex[:12]


def _jsonable(result: Any) -> dict | None:
    """fn 结果的 JSON-able 摘要（model_dump/dict 均可；不可序列化则取 str）"""
    if result is None:
        return None
    dump = getattr(result, "model_dump", None)
    if callable(dump):
        try:
            return dump(mode="json")
        except Exception:  # noqa: BLE001
            pass
    if isinstance(result, dict):
        return result
    return {"repr": str(result)[:500]}


def submit_tracked(
    *,
    kind: str,
    capability: str,
    title: str,
    fn: Callable[..., Any],
    fn_kwargs: dict | None = None,
    total: int = 100,
    category: str = "analysis",
    idempotency_key: str | None = None,
    research_run_id: str | None = None,
    payload: dict | None = None,
) -> dict:
    """submit_durable_job 的别名（旧 tracker.submit 形状的迁移入口）"""
    return submit_durable_job(
        kind=kind,
        capability=capability,
        title=title,
        fn=fn,
        fn_kwargs=fn_kwargs,
        total=total,
        category=category,
        idempotency_key=idempotency_key,
        research_run_id=research_run_id,
        payload=payload,
    )


def submit_tracked_compat(
    task_type: str,
    title: str,
    fn: Callable[..., Any],
    *args: Any,
    capability: str,
    kind: str | None = None,
    total: int = 100,
    category: str = "general",
    timeout_s: int = 1800,
    max_attempts: int = 1,
    **fn_kwargs: Any,
) -> str:
    """global_tracker.submit 的兼容签名——内部走 durable Job/Task（C3 权威切换）。

    返回 tracker task_id（str），旧调用方零改动；durable 侧经 external_ref 关联。
    """
    from packages.domain.task_tracker import global_tracker
    from packages.storage.db import session_scope
    from packages.storage.repositories import JobRepository, TaskRepository

    # 1. 落库 Job + Task（queued；create_job 默认 submitted→queued 由 claim 收敛）
    with session_scope() as session:
        job, _ = JobRepository(session).create_job(
            kind=kind or task_type,
            payload={"title": title},
            created_by="api",
        )
        job_id = job.id
        task, _ = TaskRepository(session).add_task(
            job_id=job_id,
            capability=capability,
            resource_class="default",
            timeout_s=timeout_s,
            max_attempts=max_attempts,
        )
        task_id = task.id

    # 2. 领取（leased + lease + attempt），Job → running；fn 与 Task 绑定，按 ID 领取
    with session_scope() as session:
        claimed = TaskRepository(session).claim_task_by_id(
            task_id=task_id, executor_id="api-thread"
        )
        lease_token = claimed.lease_token

    # 3. 包装 fn：进度双写 + lease 续约；成功/失败写回 durable
    def _wrapped(progress_callback=None):
        def _dual(msg: str, cur: int, tot: int) -> None:
            if progress_callback:
                progress_callback(msg, cur, tot)
            with suppress(Exception), session_scope() as session:
                JobRepository(session).update_progress(job_id, current=cur, total=tot, message=msg)
                TaskRepository(session).touch_lease(task_id, lease_token)

        try:
            result = fn(*args, progress_callback=_dual, **fn_kwargs)
        except Exception as exc:
            logger.exception("durable job %s task %s failed: %s", job_id, task_id, exc)
            with suppress(Exception), session_scope() as session:
                TaskRepository(session).fail_task(
                    task_id=task_id,
                    executor_id="api-thread",
                    lease_token=lease_token or "",
                    error_class=type(exc).__name__,
                    message=str(exc),
                )
            raise
        with suppress(Exception), session_scope() as session:
            TaskRepository(session).complete_task(
                task_id=task_id,
                executor_id="api-thread",
                lease_token=lease_token or "",
                result_ref=_jsonable(result),
            )
        return result

    # 4. tracker 驱动执行，回填 external_ref
    tracker_task_id = global_tracker.submit(
        task_type, title, _wrapped, total=total, category=category
    )
    with suppress(Exception), session_scope() as session:
        TaskRepository(session).set_external_ref(task_id, tracker_task_id)

    return tracker_task_id
