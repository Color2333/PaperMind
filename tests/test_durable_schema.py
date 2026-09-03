"""C2：原子 durable execution schema 契约测试

覆盖：Job 幂等创建、Task 领取互斥与 lease 签发、fencing（错 lease 拒绝提交）、
fail 重试→dead_letter、artifact 关联、Job 状态由子 Task 收敛、ResearchRun↔Job 关联。
"""

from __future__ import annotations

import hashlib

import pytest
from sqlalchemy import select

from packages.domain.enums import (
    JobStatus,
    TaskAttemptStatus,
    TaskStatus,
)
from packages.domain.exceptions import ConflictError, NotFoundError
from packages.storage.db import session_scope
from packages.storage.models import ResearchRun
from packages.storage.repositories import (
    ArtifactRepository,
    JobRepository,
    ResearchRunRepository,
    TaskRepository,
)


def _mk_run(session, question_id: str | None = None) -> str:
    return (
        ResearchRunRepository(session)
        .start(kind="claim_extraction", research_question_id=question_id)
        .id
    )


# ---------- Job ----------


def test_create_job_idempotent_on_key(isolated_db):
    with session_scope() as session:
        repo = JobRepository(session)
        job1, created1 = repo.create_job(
            kind="RunTopicResearch",
            payload={"topic": "diarization"},
            idempotency_key="topic:diarization:2026-09-02",
            created_by="scheduler",
        )
        job2, created2 = repo.create_job(
            kind="RunTopicResearch",
            payload={"topic": "diarization"},
            idempotency_key="topic:diarization:2026-09-02",
            created_by="scheduler",
        )
        assert created1 is True and created2 is False
        assert job1.id == job2.id


def test_job_run_association(isolated_db):
    """RESEARCH_RUN ↔ JOB：Job 挂 research_run_id，Run 侧 job_ref 弱引用同步"""
    with session_scope() as session:
        run_id = _mk_run(session)
        job, _ = JobRepository(session).create_job(
            kind="claim_extraction", research_run_id=run_id, idempotency_key="run-job-1"
        )
        run = session.get(ResearchRun, run_id)
        assert job.research_run_id == run_id
        run.job_ref = job.id  # 设计①：Run 侧保留弱引用
        session.flush()
        assert run.job_ref == job.id


# ---------- Task 领取与 lease ----------


def test_claim_leases_with_token_and_attempt(isolated_db):
    with session_scope() as session:
        job_repo = JobRepository(session)
        task_repo = TaskRepository(session)
        job, _ = job_repo.create_job(kind="RunTopicResearch")
        task, created = task_repo.add_task(
            job_id=job.id, capability="skim_paper", idempotency_key="skim:p1"
        )
        assert created is True

        claimed = task_repo.claim_task(executor_id="py-exec-1", capabilities=["skim_paper"])
        assert claimed is not None and claimed.id == task.id
        assert claimed.status is TaskStatus.leased
        assert claimed.lease_token and claimed.attempt_count == 1

        # 同一 Task 二次领取 → 无（已被 lease）
        again = task_repo.claim_task(executor_id="py-exec-2", capabilities=["skim_paper"])
        assert again is None

        # attempt 行已记录（fencing token = attempt_count = 1）
        # Job 收敛为 running
        assert job_repo.get(job.id).status is JobStatus.running


def test_complete_requires_valid_lease(isolated_db):
    with session_scope() as session:
        job, _ = JobRepository(session).create_job(kind="RunTopicResearch")
        job_id = job.id  # 事务提交后 ORM 过期——先取纯值
        TaskRepository(session).add_task(job_id=job_id, capability="skim_paper")
        claimed = TaskRepository(session).claim_task(
            executor_id="py-exec-1", capabilities=["skim_paper"]
        )
        lease_token = claimed.lease_token
        task_id = claimed.id

    with session_scope() as session:
        repo = TaskRepository(session)
        # 错误 lease → fencing 拒绝
        with pytest.raises(ConflictError):
            repo.complete_task(task_id=task_id, executor_id="py-exec-1", lease_token="wrong-token")
        # 正确 lease → succeeded
        done = repo.complete_task(
            task_id=task_id,
            executor_id="py-exec-1",
            lease_token=lease_token,
            result_ref={"artifact": "a1"},
        )
        assert done.status is TaskStatus.succeeded
        # Job 收敛：全部 Task 成功 → Job succeeded
        assert JobRepository(session).recompute_job_status(job_id).status is JobStatus.succeeded


def test_fail_retries_then_dead_letter(isolated_db):
    with session_scope() as session:
        job, _ = JobRepository(session).create_job(kind="RunTopicResearch")
        job_id = job.id
        TaskRepository(session).add_task(job_id=job_id, capability="skim_paper", max_attempts=2)
        repo = TaskRepository(session)

        # 第 1 次：claim → fail → 重入队
        t1 = repo.claim_task(executor_id="exec", capabilities=["skim_paper"])
        failed = repo.fail_task(
            task_id=t1.id,
            executor_id="exec",
            lease_token=t1.lease_token,
            error_class="network",
            message="boom",
        )
        assert failed.status is TaskStatus.queued

        # 第 2 次：claim → fail → attempt 耗尽 → dead_letter
        t2 = repo.claim_task(executor_id="exec", capabilities=["skim_paper"])
        assert t2.attempt_count == 2
        dead = repo.fail_task(
            task_id=t2.id,
            executor_id="exec",
            lease_token=t2.lease_token,
            error_class="network",
            message="boom again",
        )
        assert dead.status is TaskStatus.dead_letter

        # Job 收敛：唯一 Task dead_letter → failed
        assert JobRepository(session).recompute_job_status(job_id).status is JobStatus.failed


def test_partial_success_job(isolated_db):
    with session_scope() as session:
        job, _ = JobRepository(session).create_job(kind="RunTopicResearch")
        job_id = job.id
        repo = TaskRepository(session)
        t1, _ = repo.add_task(job_id=job_id, capability="skim_paper", seq=1, max_attempts=2)
        t2, _ = repo.add_task(job_id=job_id, capability="embed_paper", seq=2, max_attempts=2)

        c1 = repo.claim_task(executor_id="exec", capabilities=["skim_paper"])
        repo.complete_task(task_id=c1.id, executor_id="exec", lease_token=c1.lease_token)

        c2 = repo.claim_task(executor_id="exec", capabilities=["embed_paper"])
        repo.fail_task(
            task_id=c2.id,
            executor_id="exec",
            lease_token=c2.lease_token,
            error_class="llm",
            message="quota",
        )
        c3 = repo.claim_task(executor_id="exec", capabilities=["embed_paper"])
        repo.fail_task(
            task_id=c3.id,
            executor_id="exec",
            lease_token=c3.lease_token,
            error_class="llm",
            message="quota again",
        )  # 耗尽 → dead_letter

        job_row = JobRepository(session).recompute_job_status(job_id)
        assert job_row.status is JobStatus.partially_succeeded


def test_claim_respects_dependencies(isolated_db):
    with session_scope() as session:
        job, _ = JobRepository(session).create_job(kind="RunTopicResearch")
        repo = TaskRepository(session)
        t1, _ = repo.add_task(job_id=job.id, capability="download", seq=1)
        t2, _ = repo.add_task(job_id=job.id, capability="skim_paper", seq=2, depends_on=[t1.id])
        # 依赖未完成：skim 不可领取，只能领 download
        got = repo.claim_task(executor_id="exec", capabilities=["skim_paper", "download"])
        assert got.capability == "download"
        repo.complete_task(task_id=got.id, executor_id="exec", lease_token=got.lease_token)
        # 依赖完成后：skim 可领取
        got2 = repo.claim_task(executor_id="exec", capabilities=["skim_paper"])
        assert got2 is not None and got2.capability == "skim_paper"


# ---------- Artifact ----------


def test_artifact_links_to_task(isolated_db):
    with session_scope() as session:
        job, _ = JobRepository(session).create_job(kind="RunTopicResearch")
        task, _ = TaskRepository(session).add_task(job_id=job.id, capability="skim_paper")
        repo = ArtifactRepository(session)
        artifact = repo.add_artifact(
            task_id=task.id,
            kind="report",
            uri="analysis://report-1",
            content_hash=hashlib.sha256(b"report").hexdigest(),
            metadata_json={"format": "md"},
        )
        assert task.output_artifact_id == artifact.id
        assert len(repo.list_for_task(task.id)) == 1
        with pytest.raises(NotFoundError):
            repo.add_artifact(task_id="missing", kind="x", uri="u", content_hash="h")


# ---------- ResearchRun 关联 + Attempt 记录 ----------


def test_job_progress_with_run_and_attempts(isolated_db):
    with session_scope() as session:
        run_id = _mk_run(session)
        job, _ = JobRepository(session).create_job(kind="claim_extraction", research_run_id=run_id)
        repo = TaskRepository(session)
        task, _ = repo.add_task(
            job_id=job.id, capability="extract_claims", idempotency_key="claims:p1"
        )
        claimed = repo.claim_task(executor_id="py-exec", capabilities=["extract_claims"])
        done = repo.complete_task(
            task_id=claimed.id, executor_id="py-exec", lease_token=claimed.lease_token
        )
        assert done.status is TaskStatus.succeeded

        # attempt 记录：succeeded、fencing=1
        from packages.storage.models import TaskAttempt

        attempt = session.execute(select(TaskAttempt)).scalars().one()
        assert attempt.status is TaskAttemptStatus.succeeded
        assert attempt.fencing_token == 1
        assert attempt.finished_at is not None

        # 幂等重放：同 key 再展开不新增 Task
        _, created_again = repo.add_task(
            job_id=job.id, capability="extract_claims", idempotency_key="claims:p1"
        )
        assert created_again is False


# ---------- P0：并发 claim 原子性（多 Executor 场景） ----------


def test_concurrent_claim_single_winner(tmp_path, monkeypatch):
    """两个并发连接抢同一个 queued Task：CAS 保证恰好一个赢家（P0 修复回归）。

    用独立文件库（每会话独立连接 + WAL）模拟多 Executor 进程的真实并发；
    StaticPool 单连接会共享事务上下文，无法表达这个语义。
    """
    import threading

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import NullPool

    from packages.storage import db as db_module
    from packages.storage.models import Base

    engine = create_engine(
        f"sqlite:///{tmp_path}/conc.db",
        connect_args={"check_same_thread": False, "timeout": 30},
        poolclass=NullPool,
    )
    Base.metadata.create_all(bind=engine)
    maker = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    monkeypatch.setattr(db_module, "engine", engine)
    monkeypatch.setattr(db_module, "SessionLocal", maker)

    from packages.storage.repositories import JobRepository

    with maker() as session:
        job, _ = JobRepository(session).create_job(kind="skim_paper")
        TaskRepository(session).add_task(job_id=job.id, capability="skim_paper")
        global_job_id = job.id
        session.commit()

    results: list[str] = []
    barrier = threading.Barrier(2)

    def _claim(idx: int) -> None:
        barrier.wait()
        session = maker()
        try:
            claimed = TaskRepository(session).claim_task(
                executor_id=f"exec-{idx}", capabilities=["skim_paper"]
            )
            results.append("win" if claimed is not None else "lose")
            session.commit()
        except Exception:
            session.rollback()
            results.append("error")
        finally:
            session.close()

    t1 = threading.Thread(target=_claim, args=(1,))
    t2 = threading.Thread(target=_claim, args=(2,))
    t1.start()
    t2.start()
    t1.join(30)
    t2.join(30)

    assert sorted(results) == ["lose", "win"], f"应恰好一个赢家: {results}"

    with maker() as session:
        task = TaskRepository(session).list_for_job(global_job_id)[0]
        assert task.attempt_count == 1, "并发输家不得重复计 attempt"
        assert task.status is TaskStatus.leased
    engine.dispose()
