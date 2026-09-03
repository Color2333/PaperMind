"""P1 lease/fencing 契约测试（第二轮 REVIEW 点名四类）：

1. 错误 executor + 正确 token → 拒绝；
2. lease 过期后 heartbeat 不续约 / complete 被拒；
3. 已完成的 Task 上 heartbeat → ok=False；
4. 未注册 capability 越权 claim → Go 侧能力交集（core/server_test.go），
   Python 侧以 claim 能力不匹配返回 None 验证同语义。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from packages.domain.enums import TaskStatus
from packages.domain.exceptions import ConflictError
from packages.storage.db import session_scope
from packages.storage.repositories import JobRepository, TaskRepository


def _mk_task(capability: str = "skim_paper") -> tuple[str, str]:
    with session_scope() as session:
        job, _ = JobRepository(session).create_job(kind="test_kind")
        task, _ = TaskRepository(session).add_task(job_id=job.id, capability=capability)
        return job.id, task.id


def test_wrong_executor_with_valid_token_rejected(isolated_db):
    """契约 1：错误 executor + 正确 token → complete/fail 拒绝"""
    _, task_id = _mk_task()
    with session_scope() as session:
        claimed = TaskRepository(session).claim_task_by_id(task_id=task_id, executor_id="exec-a")
        token = claimed.lease_token

    with session_scope() as session, __import__("pytest").raises(ConflictError, match="exec-b"):
        TaskRepository(session).complete_task(
            task_id=task_id, executor_id="exec-b", lease_token=token
        )
    with session_scope() as session, __import__("pytest").raises(ConflictError):
        TaskRepository(session).fail_task(
            task_id=task_id, executor_id="exec-b", lease_token=token, error_class="x"
        )


def test_expired_lease_cannot_heartbeat_or_complete(isolated_db):
    """契约 2：lease 过期后 heartbeat 不续约、complete 拒绝（迟到写入）"""
    _, task_id = _mk_task()
    with session_scope() as session:
        claimed = TaskRepository(session).claim_task_by_id(task_id=task_id, executor_id="exec-a")
        token = claimed.lease_token
        # 时钟推进：把 lease 过期时间拨到过去
        claimed.lease_expires_at = datetime.now(UTC) - timedelta(seconds=5)
        session.flush()

    with session_scope() as session:
        ok, cancel_requested = TaskRepository(session).heartbeat_lease(
            task_id=task_id, lease_token=token
        )
        assert ok is False  # 过期 lease 不得复活
    with session_scope() as session, __import__("pytest").raises(ConflictError, match="过期"):
        TaskRepository(session).complete_task(
            task_id=task_id, executor_id="exec-a", lease_token=token
        )


def test_heartbeat_after_completion_returns_not_ok(isolated_db):
    """契约 3：已完成 Task 的 heartbeat → ok=False（token 已清空）"""
    _, task_id = _mk_task()
    with session_scope() as session:
        claimed = TaskRepository(session).claim_task_by_id(task_id=task_id, executor_id="exec-a")
        token = claimed.lease_token
        TaskRepository(session).complete_task(
            task_id=task_id, executor_id="exec-a", lease_token=token
        )

    with session_scope() as session:
        ok, _ = TaskRepository(session).heartbeat_lease(task_id=task_id, lease_token=token)
        assert ok is False
        assert TaskRepository(session).get(task_id).status is TaskStatus.succeeded


def test_unregistered_capability_claim_yields_nothing(isolated_db):
    """契约 4（Python 侧同语义）：claim 能力不匹配 → None（Go 侧交集测试在 core/）"""
    _, _ = _mk_task(capability="embed_paper")
    with session_scope() as session:
        assert (
            TaskRepository(session).claim_task(executor_id="exec-a", capabilities=["skim_paper"])
            is None
        )
        claimed = TaskRepository(session).claim_task(
            executor_id="exec-a", capabilities=["embed_paper"]
        )
        assert claimed is not None
