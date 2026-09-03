"""durable-state 内部 API（P0 闭环的权威状态面）

Go Core 的唯一任务状态来源：claim/complete/fail/heartbeat/cancel/status/reclaim
全部落到 SQLAlchemy durable 仓储（jobs/tasks/attempts 表）——**权威状态只有一份**。

安全契约：
- 挂载条件：settings.durable_state_token 非空才挂载（未配置 = 不暴露此面）；
- 认证：`X-Internal-Token` 必须与配置一致（与用户面 JWT/API-token 认证互相独立）；
- 部署边界：Go Core 与本端点同内网/loopback 通信，不越过反向代理对外暴露。

协议（plain JSON，不走 Executor 信封——信封是 Go↔Executor 的外部协议）：
- POST /internal/durable/tasks/claim                 {executor_id, capabilities}
- POST /internal/durable/tasks/{id}/heartbeat        {lease_token}
- POST /internal/durable/tasks/{id}/complete         {executor_id, lease_token, result}
- POST /internal/durable/tasks/{id}/fail             {executor_id, lease_token, error_class, message}
- POST /internal/durable/tasks/{id}/cancel-execution {executor_id, lease_token}  # 协作取消回执
- POST /internal/durable/tasks/{id}/cancel           {}                           # 控制面取消
- GET  /internal/durable/tasks/{id}                                               # 状态快照
- POST /internal/durable/reclaim                     {backoff_s}                  # Reconciler
- GET  /internal/durable/queue/stats
- POST /internal/durable/queue/pause | resume
"""

from __future__ import annotations

import logging
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select

from packages.config import get_settings
from packages.domain.enums import JobStatus, TaskStatus
from packages.domain.exceptions import ConflictError, NotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/durable")


def require_internal_token(request: Request) -> None:
    """内部令牌校验（与 AuthMiddleware 的用户面凭证互相独立）"""
    expected = get_settings().durable_state_token
    if not expected:
        raise HTTPException(status_code=403, detail="internal state API disabled")
    if request.headers.get("X-Internal-Token", "") != expected:
        raise HTTPException(status_code=401, detail="invalid internal token")


router.dependencies.append(Depends(require_internal_token))


def _claimed_payload(task) -> dict:  # noqa: ANN001
    """claim 响应：Executor 执行所需的全部 fencing 凭证"""
    return {
        "task_id": task.id,
        "attempt_id": f"{task.id}:{task.attempt_count}",
        "capability": task.capability,
        "input": dict(task.input_ref or {}),
        "resource_class": task.resource_class,
        "timeout_s": task.timeout_s,
        "attempt_no": task.attempt_count,
        "fencing_token": task.attempt_count,
        "lease_token": task.lease_token,
    }


def _task_snapshot(task) -> dict:  # noqa: ANN001
    return {
        "task_id": task.id,
        "job_id": task.job_id,
        "capability": task.capability,
        "status": task.status.value if hasattr(task.status, "value") else str(task.status),
        "attempt_count": task.attempt_count,
        "max_attempts": task.max_attempts,
        "input": dict(task.input_ref or {}),
        "last_error": task.last_error,
    }


@router.post("/tasks/claim")
def claim_task(body: dict) -> dict:
    from packages.storage.db import session_scope
    from packages.storage.repositories import TaskRepository

    executor_id = str(body.get("executor_id") or "")
    capabilities = list(body.get("capabilities") or [])
    if not executor_id or not capabilities:
        raise HTTPException(status_code=400, detail="executor_id and capabilities required")
    with session_scope() as session:
        claimed = TaskRepository(session).claim_task(
            executor_id=executor_id, capabilities=capabilities
        )
        if claimed is None:
            return {"task": None}
        return {"task": _claimed_payload(claimed)}


def _fencing_op(task_id: str, body: dict, op_name: str) -> dict:
    """带 fencing 校验的执行提交；冲突→409，不存在→404"""
    from packages.storage.db import session_scope
    from packages.storage.repositories import TaskRepository

    executor_id = str(body.get("executor_id") or "")
    lease_token = str(body.get("lease_token") or "")
    if not lease_token:
        raise HTTPException(status_code=400, detail="lease_token required")
    try:
        with session_scope() as session:
            repo = TaskRepository(session)
            if op_name == "complete":
                task = repo.complete_task(
                    task_id=task_id,
                    executor_id=executor_id,
                    lease_token=lease_token,
                    result_ref=body.get("result") or {},
                )
            elif op_name == "fail":
                task = repo.fail_task(
                    task_id=task_id,
                    executor_id=executor_id,
                    lease_token=lease_token,
                    error_class=str(body.get("error_class") or "unknown"),
                    message=str(body.get("message") or ""),
                )
            else:  # cancel-execution
                task = repo.cancel_task_execution(
                    task_id=task_id, executor_id=executor_id, lease_token=lease_token
                )
            return {"ok": True, "status": task.status.value}
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/tasks/{task_id}/heartbeat")
def heartbeat(task_id: str, body: dict) -> dict:
    from packages.storage.db import session_scope
    from packages.storage.repositories import TaskRepository

    lease_token = str(body.get("lease_token") or "")
    if not lease_token:
        raise HTTPException(status_code=400, detail="lease_token required")
    try:
        with session_scope() as session:
            ok, cancel_requested = TaskRepository(session).heartbeat_lease(
                task_id=task_id, lease_token=lease_token
            )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": ok, "cancel_requested": cancel_requested}


@router.post("/tasks/{task_id}/complete")
def complete(task_id: str, body: dict) -> dict:
    return _fencing_op(task_id, body, "complete")


@router.post("/tasks/{task_id}/fail")
def fail(task_id: str, body: dict) -> dict:
    return _fencing_op(task_id, body, "fail")


@router.post("/tasks/{task_id}/cancel-execution")
def cancel_execution(task_id: str, body: dict) -> dict:
    return _fencing_op(task_id, body, "cancel-execution")


@router.post("/tasks/{task_id}/cancel")
def cancel_task(task_id: str) -> dict:
    """控制面取消单个 Task：queued→cancelled；leased→协作取消标记（heartbeat 探测）"""
    from packages.storage.db import session_scope
    from packages.storage.repositories import JobRepository, TaskRepository

    with session_scope() as session:
        repo = TaskRepository(session)
        task = repo.get(task_id)
        if task.status == TaskStatus.queued:
            task.status = TaskStatus.cancelled
            task.lease_token = None
            task.lease_expires_at = None
            session.flush()
            JobRepository(session).recompute_job_status(task.job_id)
            return {"ok": True, "status": task.status.value}
        if task.status in (TaskStatus.leased, TaskStatus.running):
            JobRepository(session).set_status(task.job_id, JobStatus.cancelling)
            session.flush()
            # heartbeat 探测 cancelling → cancel_requested → Executor 安全点退出
            return {"ok": True, "status": "leased", "cancel_requested": True}
        return {"ok": False, "status": task.status.value}


@router.get("/tasks/{task_id}")
def task_status(task_id: str) -> dict:
    from packages.storage.db import session_scope
    from packages.storage.repositories import TaskRepository

    try:
        with session_scope() as session:
            return {"task": _task_snapshot(TaskRepository(session).get(task_id))}
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/reclaim")
def reclaim(body: dict) -> dict:
    """Reconciler 入口：回收过期 lease（requeued / dead_letter）"""
    from packages.storage.db import session_scope
    from packages.storage.repositories import TaskRepository

    backoff_s = int(body.get("backoff_s") or 60)
    with session_scope() as session:
        outcomes = TaskRepository(session).reclaim_expired_leases(backoff_s=backoff_s)
    return {"outcomes": outcomes}


@router.get("/queue/stats")
def queue_stats() -> dict:
    from packages.storage.db import session_scope
    from packages.storage.models import DurableTask

    with session_scope() as session:
        rows = session.execute(select(DurableTask.status)).scalars()
        counts = Counter(str(s.value) for s in rows)
    return {"counts": dict(counts)}


@router.post("/queue/pause")
def queue_pause() -> dict:
    from packages.storage.db import session_scope
    from packages.storage.repositories import durable as durable_repo

    with session_scope() as session:
        durable_repo.pause_queue(session)
    return {"paused": True}


@router.post("/queue/resume")
def queue_resume() -> dict:
    from packages.storage.db import session_scope
    from packages.storage.repositories import durable as durable_repo

    with session_scope() as session:
        durable_repo.resume_queue(session)
    return {"paused": False}
