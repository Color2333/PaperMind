"""C11：渐进迁移与恢复测试（设计③ §8 验收用例）

设计③要求替代 `recover_stale_running` 破坏性恢复的五场景：
1. lease 过期回收 → 重入队 → 重新执行（非破坏性恢复）
2. 重复领取互斥（同 Task 不可被两个 Executor 同时持有）
3. 部分失败收敛（partial）
4. 迟到写入拒绝（fencing）
5. batch_jobs 创建 → durable ProcessUnreadBatch 镜像（渐进迁移）
"""

from __future__ import annotations

from packages.application.commands.batch import create_batch_job
from packages.application.commands.reconciler import run_reconcile
from packages.application.commands.workflows import expand_job
from packages.domain.enums import JobStatus, TaskStatus
from packages.domain.exceptions import ConflictError
from packages.storage.db import session_scope
from packages.storage.models import DurableTask
from packages.storage.repositories import JobRepository, TaskRepository

# ---------- 场景 1：lease 过期 → 非破坏性回收 ----------


def test_scenario_lease_expiry_non_destructive_recovery(isolated_db):
    with session_scope() as session:
        job, _ = JobRepository(session).create_job(kind="RunTopicResearch")
        job_id = job.id
        repo = TaskRepository(session)
        t, _ = repo.add_task(job_id=job_id, capability="skim_paper", max_attempts=3)
        task_id = t.id

        claimed = repo.claim_task_by_id(task_id=task_id, executor_id="executor-a")
        # Executor 强杀（不 cleanup）→ lease 自然过期
        claimed.lease_expires_at = __import__("datetime").datetime.now(
            __import__("datetime").UTC
        ) - __import__("datetime").timedelta(seconds=120)
        session.flush()

        run_reconcile(session)  # 回收（requeue，非 failed）
        refreshed = session.get(DurableTask, task_id)
        assert refreshed.status is TaskStatus.queued
        assert refreshed.attempt_count == 1  # 已计 attempt

        # 重新执行 → 成功
        re_claimed = repo.claim_task_by_id(task_id=task_id, executor_id="executor-b")
        repo.complete_task(
            task_id=re_claimed.id, executor_id="executor-b", lease_token=re_claimed.lease_token
        )
        assert JobRepository(session).get(job_id).status is JobStatus.succeeded


# ---------- 场景 2：重复领取互斥 ----------


def test_scenario_double_claim_prevented(isolated_db):
    with session_scope() as session:
        job, _ = JobRepository(session).create_job(kind="RunTopicResearch")
        repo = TaskRepository(session)
        repo.add_task(job_id=job.id, capability="skim_paper")

        c1 = repo.claim_task(executor_id="exec-a", capabilities=["skim_paper"])
        c2 = repo.claim_task(executor_id="exec-b", capabilities=["skim_paper"])
        assert c1 is not None
        assert c2 is None  # 已被 lease，不可重复领取


# ---------- 场景 3：部分失败收敛 partial ----------


def test_scenario_partial_failure_convergence(isolated_db):
    with session_scope() as session:
        job, _ = JobRepository(session).create_job(kind="RunTopicResearch")
        job_id = job.id
        repo = TaskRepository(session)
        for i, cap in enumerate(["skim_paper", "embed_paper", "deep_read_paper"]):
            repo.add_task(job_id=job_id, capability=cap, seq=i, max_attempts=1)

        # skim 成功、embed 失败耗尽、deep_read 成功
        c1 = repo.claim_task(executor_id="e", capabilities=["skim_paper"])
        repo.complete_task(task_id=c1.id, executor_id="e", lease_token=c1.lease_token)
        c2 = repo.claim_task(executor_id="e", capabilities=["embed_paper"])
        repo.fail_task(
            task_id=c2.id,
            executor_id="e",
            lease_token=c2.lease_token,
            error_class="llm",
            message="quota",
        )
        c3 = repo.claim_task(executor_id="e", capabilities=["deep_read_paper"])
        repo.complete_task(task_id=c3.id, executor_id="e", lease_token=c3.lease_token)

        row = JobRepository(session).recompute_job_status(job_id)
        assert row.status is JobStatus.partially_succeeded


# ---------- 场景 4：迟到写入拒绝 ----------


def test_scenario_late_write_rejected(isolated_db):
    with session_scope() as session:
        job, _ = JobRepository(session).create_job(kind="RunTopicResearch")
        repo = TaskRepository(session)
        t, _ = repo.add_task(job_id=job.id, capability="skim_paper", max_attempts=2)
        task_id = t.id

        c1 = repo.claim_task_by_id(task_id=task_id, executor_id="exec-1")
        old_token = c1.lease_token

        # 模拟 Executor 强杀 → Reconciler 回收 → 新 Executor 领取
        c1.lease_expires_at = __import__("datetime").datetime.now(
            __import__("datetime").UTC
        ) - __import__("datetime").timedelta(seconds=120)
        session.flush()
        run_reconcile(session)
        c2 = repo.claim_task_by_id(task_id=task_id, executor_id="exec-2")

        # 旧 Executor 迟到 complete → 拒绝
        try:
            repo.complete_task(task_id=task_id, executor_id="exec-1", lease_token=old_token)
            raise AssertionError("迟到写入应被拒")
        except ConflictError:
            pass

        # 新 Executor 写入成功
        done = repo.complete_task(task_id=task_id, executor_id="exec-2", lease_token=c2.lease_token)
        assert done.status is TaskStatus.succeeded


# ---------- 场景 5：batch_jobs 创建 → durable 镜像 ----------


def test_scenario_batch_creates_durable_job(isolated_db):
    with session_scope() as session:
        result = create_batch_job(session, kind="skim", paper_ids=["p1", "p2"], created_by="agent")
        assert "durable_job_id" in result

        durable_job = JobRepository(session).get(result["durable_job_id"])
        assert durable_job.kind == "ProcessUnreadBatch"
        assert durable_job.idempotency_key == f"batch:{result['job_id']}"

        tasks = TaskRepository(session).list_for_job(durable_job.id)
        assert len(tasks) == 2  # 2 篇 × skim
        assert all(t.capability == "skim_paper" for t in tasks)

        # 幂等：同 batch_job 不会重复展开（expand 不新增）
        created_again = expand_job(session, durable_job.id)
        assert created_again == []


# ---------- 场景 6：幂等重复提交去重 ----------


def test_scenario_idempotent_job_submission(isolated_db):
    with session_scope() as session:
        repo = JobRepository(session)
        j1, c1 = repo.create_job(kind="RunTopicResearch", idempotency_key="topic:test:unique")
        j2, c2 = repo.create_job(kind="RunTopicResearch", idempotency_key="topic:test:unique")
        assert c1 is True and c2 is False
        assert j1.id == j2.id
