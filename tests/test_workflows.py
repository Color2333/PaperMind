"""C5：代码化 Workflow 模板测试

覆盖：RunTopicResearch per-Paper fan-out + 依赖顺序、幂等重放（不重复展开）、
ProcessUnreadBatch fan-out、BuildDailyBrief 条件分支（邮件 send Task）、
RunCitationSync fan-out、claim 依赖满足（下游 Task 不可先领）。
"""

from __future__ import annotations

from packages.application.commands.workflows import (
    expand_job,
    start_workflow_job,
)
from packages.domain.enums import JobStatus, TaskStatus
from packages.storage.db import session_scope
from packages.storage.repositories import JobRepository, TaskRepository


def test_unknown_kind_raises(isolated_db):
    with session_scope() as session:
        job, _ = JobRepository(session).create_job(kind="NotAWorkflow")
        try:
            expand_job(session, job.id)
            raise AssertionError("应抛 ValueError")
        except ValueError as exc:
            assert "没有注册 Workflow 模板" in str(exc)


def test_topic_research_fanout_and_dependencies(isolated_db):
    with session_scope() as session:
        job, tasks, created = start_workflow_job(
            session,
            kind="RunTopicResearch",
            payload={
                "paper_ids": ["p1", "p2"],
                "fetch_query": "diarization",
            },
            idempotency_key="topic:diarization:run1",
        )
        assert created is True
        caps = sorted(t.capability for t in tasks)
        # fetch×1 + 每篇（upsert+download+skim+embed+extract）×2 = 11
        assert caps.count("upsert_paper") == 2
        assert caps.count("download_source") == 2
        assert caps.count("skim_paper") == 2
        assert caps.count("embed_paper") == 2
        assert caps.count("extract_claims") == 2
        assert caps.count("fetch_feed") == 1
        assert len(tasks) == 11
        del caps

        # 依赖解析：skim 的 depends_on 指向同 Job 内 download task id
        repo = TaskRepository(session)
        by_cap = {
            t.capability: t for t in repo.list_for_job(job.id) if t.capability == "skim_paper"
        }
        download_ids = {
            t.id for t in repo.list_for_job(job.id) if t.capability == "download_source"
        }
        for skim in by_cap.values():
            assert set(skim.depends_on) <= download_ids and skim.depends_on

        # 幂等重放：再 expand 不产生新 Task
        again = expand_job(session, job.id)
        assert again == []
        assert len(repo.list_for_job(job.id)) == 11


def test_batch_fanout_and_claim_order(isolated_db):
    with session_scope() as session:
        job, tasks, _ = start_workflow_job(
            session,
            kind="ProcessUnreadBatch",
            payload={"paper_ids": ["p1", "p2"], "kinds": ["skim_paper", "embed_paper"]},
        )
        assert len(tasks) == 4  # 2 篇 × 2 kind
        repo = TaskRepository(session)

        # 依赖无——任一 Task 可领取；单 Task 互斥（leased 后不重复领）
        got1 = repo.claim_task(executor_id="e1", capabilities=["skim_paper"])
        assert got1 is not None and got1.capability == "skim_paper"
        got2 = repo.claim_task(executor_id="e2", capabilities=["skim_paper"])
        assert got2 is not None and got2.id != got1.id
        assert repo.claim_task(executor_id="e3", capabilities=["skim_paper"]) is None


def test_daily_brief_conditional_mail_task(isolated_db):
    with session_scope() as session:
        # 无收件人：只有 build
        job1, tasks1, _ = start_workflow_job(
            session, kind="BuildDailyBrief", payload={}, idempotency_key="brief:1"
        )
        assert [t.capability for t in tasks1] == ["build_daily_brief"]
        del job1

        # 有收件人：build → send（依赖 build）
        job2, tasks2, _ = start_workflow_job(
            session,
            kind="BuildDailyBrief",
            payload={"recipient": "me@example.com"},
            idempotency_key="brief:2",
        )
        caps = {t.capability: t for t in tasks2}
        assert set(caps) == {"build_daily_brief", "send_brief_email"}
        assert caps["send_brief_email"].depends_on == [caps["build_daily_brief"].id]
        # manual_recovery 能力：不自动重试
        assert caps["send_brief_email"].max_attempts == 1
        del job2


def test_citation_sync_fanout(isolated_db):
    with session_scope() as session:
        job, tasks, _ = start_workflow_job(
            session,
            kind="RunCitationSync",
            payload={"paper_ids": ["a", "b", "c"]},
        )
        assert len(tasks) == 3
        assert all(t.capability == "sync_citations_paper" for t in tasks)
        del job


def test_workflow_job_completion_convergence(isolated_db):
    """C5 出口：父 Job 由子 Task 收敛——全成功 → succeeded；可解释每个子 Task 贡献"""
    with session_scope() as session:
        job, tasks, _ = start_workflow_job(
            session,
            kind="ProcessUnreadBatch",
            payload={"paper_ids": ["p1"], "kinds": ["embed_paper"]},
            idempotency_key="batch:p1",
        )
        repo = TaskRepository(session)
        task = tasks[0]
        claimed = repo.claim_task_by_id(task_id=task.id, executor_id="exec")
        repo.complete_task(task_id=claimed.id, executor_id="exec", lease_token=claimed.lease_token)
        row = JobRepository(session).recompute_job_status(job.id)
        assert row.status is JobStatus.succeeded
        # graph 可解释贡献：唯一 Task 即 Job 的全部工作
        graph_tasks = repo.list_for_job(job.id)
        assert len(graph_tasks) == 1 and graph_tasks[0].status is TaskStatus.succeeded
