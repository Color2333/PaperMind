"""Stage C1：batch consumer 移出 API 进程

- 守卫：API 入口不再引用/启动 batch consumer；消费职责归 worker。
- 行为：poll_once 单步领取→处理→收尾（成功计数、失败计数、完成状态）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from packages.application.commands.batch import create_batch_job, get_batch_job
from packages.application.commands.jobs import cancel_job, pause_queue, resume_queue, retry_job
from packages.application.commands.workflows import start_workflow_job
from packages.domain.enums import JobStatus, TaskStatus
from packages.domain.schemas import PaperCreate
from packages.integrations.llm_client import LLMClient
from packages.storage.db import session_scope
from packages.storage.models import Paper
from packages.storage.repositories import (
    BatchJobRepository,
    JobRepository,
    PaperRepository,
    TaskRepository,
)

API_MAIN = Path(__file__).resolve().parents[1] / "apps" / "api" / "main.py"
WORKER_MAIN = Path(__file__).resolve().parents[1] / "apps" / "worker" / "main.py"


def test_batch_consumer_retired_everywhere():
    """C11 退出口守卫：batch_jobs 消费者已全局退役（API 与 worker 均不引用）"""
    api_src = API_MAIN.read_text()
    assert "batch_consumer" not in api_src, "API 入口仍引用 batch_consumer"
    assert "_batch_lifespan" not in api_src, "API lifespan 仍启动任务消费"

    worker_src = WORKER_MAIN.read_text()
    assert "batch_consumer" not in worker_src, (
        "worker 仍引用 batch_consumer——C11 退出口要求批处理走 durable 任务"
    )
    assert "ExecutorRunner" in worker_src, "worker 应内置 Executor 宿主（C7）"


@pytest.fixture()
def c1_env(isolated_db, monkeypatch):
    def _fake_embed(self, text, dimensions=1536):
        return [0.5] * 8

    monkeypatch.setattr(LLMClient, "embed_text", _fake_embed)
    return isolated_db


def _mk_paper(session, arxiv_id: str) -> str:
    return (
        PaperRepository(session)
        .upsert_paper(
            PaperCreate(title=f"C1 paper {arxiv_id}", abstract="abstract.", arxiv_id=arxiv_id)
        )
        .id
    )


def _make_job(kind: str, paper_ids: list[str]) -> str:
    with session_scope() as session:
        job = BatchJobRepository(session).create(kind=kind, paper_ids=paper_ids, created_by="test")
        return job.id


def _job_row(job_id: str):
    with session_scope() as session:
        job = BatchJobRepository(session).get(job_id)
        return {
            "status": job.status,
            "done": job.done,
            "failed": job.failed,
            "error_log": job.error_log,
        }


def test_batch_embed_flows_through_durable_tasks(c1_env):
    """C11 退出口：批量入口 → durable per-Paper 任务 → InlineExecutor 执行 → 投影收敛"""
    from tests.helpers.inline_executor import InlineExecutor

    with session_scope() as session:
        pid = _mk_paper(session, "2608.9101")
        result = create_batch_job(session, kind="embed", paper_ids=[pid])

    durable_job_id = result["durable_job_id"]
    InlineExecutor(capabilities=["embed_paper"]).run_until_idle()

    with session_scope() as session:
        paper = session.get(Paper, pid)
        assert paper.embedding is not None
    with session_scope() as session:
        row = get_batch_job(session, result["job_id"])
    assert row["status"] == "succeeded"
    assert row["done"] == 1 and row["failed"] == 0
    assert row["durable_job_id"] == durable_job_id


def test_batch_paper_failure_does_not_block_others(c1_env, monkeypatch):
    """C11：单篇失败不阻断批次（durable per-Paper 任务隔离）"""
    from packages.ai.pipelines import PaperPipelines
    from tests.helpers.inline_executor import InlineExecutor

    with session_scope() as session:
        p1 = _mk_paper(session, "2608.9102")
        p2 = _mk_paper(session, "2608.9103")
        result = create_batch_job(session, kind="embed", paper_ids=[p1, p2])
        job_id = result["job_id"]

    def _boom_maybe_proposal(self, paper_id):  # 只对第一篇失败（部分成功语义）
        if str(paper_id) == str(p1):
            raise RuntimeError("embed exploded")
        return {"proposal": {"kind": "embed_paper", "paper_id": str(paper_id), "vector": [0.1]}}

    monkeypatch.setattr(PaperPipelines, "embed_paper_proposal", _boom_maybe_proposal)

    InlineExecutor(capabilities=["embed_paper"]).run_until_idle()

    with session_scope() as session:
        row = get_batch_job(session, job_id)
    assert row["failed"] >= 1 and row["done"] >= 1  # 部分成功
    assert "embed exploded" in json.dumps(row["error_log"])


def test_batch_empty_queue_no_tasks(c1_env):
    """空批次不可创建（agent 工具层拒绝）——durable 侧无遗留任务"""
    from sqlalchemy import select as _select

    from packages.storage.models import DurableTask

    with session_scope() as session:
        assert session.execute(_select(DurableTask)).scalars().all() == []


def test_cancel_job_cancels_queued_tasks(isolated_db):
    with session_scope() as session:
        job, tasks, _ = start_workflow_job(
            session,
            kind="ProcessUnreadBatch",
            payload={"paper_ids": ["p1", "p2"], "kinds": ["embed_paper"]},
        )
        job_id = job.id
        assert len(tasks) == 2

    counts = cancel_job(job_id)
    assert counts["cancelled"] == 2

    with session_scope() as session:
        assert JobRepository(session).get(job_id).status is JobStatus.cancelled
        for t in TaskRepository(session).list_for_job(job_id):
            assert t.status is TaskStatus.cancelled


def test_retry_job_requeues_dead_letter(isolated_db):
    with session_scope() as session:
        job, tasks, _ = start_workflow_job(
            session,
            kind="ProcessUnreadBatch",
            payload={"paper_ids": ["p1"], "kinds": ["embed_paper"]},
        )
        job_id = job.id
        task_id = tasks[0].id

    with session_scope() as session:
        repo = TaskRepository(session)
        claimed = repo.claim_task_by_id(task_id=task_id, executor_id="e1")
        repo.fail_task(
            task_id=claimed.id,
            executor_id="e1",
            lease_token=claimed.lease_token,
            error_class="test",
            message="fail for retry",
            # max_attempts=3 默认，1 次不 dead_letter——先耗尽
        )
        # 逐次耗尽
        for _ in range(2):
            c = repo.claim_task(executor_id="e1", capabilities=["embed_paper"])
            if c is None:
                break
            repo.fail_task(
                task_id=c.id,
                executor_id="e1",
                lease_token=c.lease_token,
                error_class="test",
                message="fail",
            )
        assert repo.get(task_id).status is TaskStatus.dead_letter

    retried = retry_job(job_id)
    assert retried["retried"] == 1

    with session_scope() as session:
        assert TaskRepository(session).get(task_id).status is TaskStatus.queued


def test_pause_resume_queue(isolated_db):
    """P0：pause 持久化到 system_flags——跨进程 claim 一致可见"""
    from packages.storage.db import session_scope as _scope
    from packages.storage.repositories import durable as durable_repo

    with session_scope() as session:
        start_workflow_job(
            session,
            kind="ProcessUnreadBatch",
            payload={"paper_ids": ["p1"], "kinds": ["embed_paper"]},
        )

    pause_queue()
    with _scope() as session:
        assert durable_repo._queue_paused(session)
        assert (
            TaskRepository(session).claim_task(executor_id="e", capabilities=["embed_paper"])
            is None
        )

    resume_queue()
    with _scope() as session:
        assert not durable_repo._queue_paused(session)
        assert (
            TaskRepository(session).claim_task(executor_id="e", capabilities=["embed_paper"])
            is not None
        )
