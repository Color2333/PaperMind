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
    """第三轮 REVIEW：依赖必须用 logical node key 解析——逐 paper 断言精确边"""
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
        repo = TaskRepository(session)
        all_tasks = repo.list_for_job(job.id)
        # fetch×1 + 每篇（upsert+download+skim+embed+extract）×2 = 11
        assert len(all_tasks) == 11

        # 按 idempotency_key（logical node key）索引——精确断言每篇的边
        by_key = {t.idempotency_key: t for t in all_tasks}
        for pid in ("p1", "p2"):
            upsert = by_key[f"{job.id}:upsert:{pid}"]
            download = by_key[f"{job.id}:download:{pid}"]
            skim = by_key[f"{job.id}:skim:{pid}"]
            embed = by_key[f"{job.id}:embed:{pid}"]
            claims = by_key[f"{job.id}:claims:{pid}"]
            fetch = by_key[f"{job.id}:fetch"]
            # 精确边（不得错连到别的 paper）
            assert upsert.depends_on == [fetch.id]
            assert download.depends_on == [upsert.id]
            assert skim.depends_on == [download.id]
            assert embed.depends_on == [upsert.id]
            assert claims.depends_on == [skim.id]

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
    """send 节点：build 完成且 result 就绪后，下一轮 expand 才绑定展开（输出绑定）"""
    with session_scope() as session:
        # 无收件人：只有 build
        job1, tasks1, _ = start_workflow_job(
            session, kind="BuildDailyBrief", payload={}, idempotency_key="brief:1"
        )
        assert [t.capability for t in tasks1] == ["daily_brief_publish"]
        del job1

        # 有收件人：首轮只展开 build（send 等 build 的 result）
        job2, tasks2, _ = start_workflow_job(
            session,
            kind="BuildDailyBrief",
            payload={"recipient": "me@example.com"},
            idempotency_key="brief:2",
        )
        assert [t.capability for t in tasks2] == ["daily_brief_publish"]
        build = next(t for t in tasks2 if t.capability == "daily_brief_publish")

        # build 未完成 → expand 不产生 send
        assert expand_job(session, job2.id) == []

        # 模拟 build 完成（result_ref 携带 content_id）→ 下一轮展开 send
        build.status = TaskStatus.succeeded
        build.input_ref = {**build.input_ref, "result_ref": {"content_id": "gc-1", "title": "简报"}}
        session.flush()
        send_tasks = expand_job(session, job2.id)
        assert [t.capability for t in send_tasks] == ["send_brief_email"]
        send = send_tasks[0]
        assert send.depends_on == [build.id]
        assert send.input_ref["recipient"] == "me@example.com"
        assert send.input_ref["content_id"] == "gc-1"  # 输出绑定已解析
        assert send.max_attempts == 1  # manual_recovery
        del job2


def test_upstream_failure_propagates_and_job_converges(isolated_db):
    """第三轮 REVIEW：前驱 dead_letter → 下游 skipped（cancelled）→ Job 确定收敛"""
    from packages.application.commands.reconciler import run_reconcile

    with session_scope() as session:
        job, tasks, _ = start_workflow_job(
            session,
            kind="RunTopicResearch",
            payload={"paper_ids": ["ok1", "bad1"]},  # 无 fetch_query——upsert 立即可建
            idempotency_key="topic:prop:1",
        )
        del job
        from packages.storage.repositories import TaskRepository as _TR

        all_tasks = _TR(session).list_for_job(tasks[0].job_id)
        by_key = {t.idempotency_key: t for t in all_tasks}

        # ok1 全链成功；bad1 的 upsert 失败进 dead_letter（max_attempts=1 直接推到终态）
        for pid in ("ok1",):
            for step in ("upsert", "download", "skim", "embed", "claims"):
                t = by_key[f"{tasks[0].job_id}:{step}:{pid}"]
                t.status = TaskStatus.succeeded
        bad_upsert = by_key[f"{tasks[0].job_id}:upsert:bad1"]
        bad_upsert.status = TaskStatus.dead_letter
        bad_upsert.max_attempts = 1
        session.flush()

        # Reconciler 驱动失败传播：bad1 链的下游全部 skipped
        result = run_reconcile(session)
        assert result["skipped"].get(tasks[0].job_id, 0) >= 3  # download/skim/embed/claims ≥3

        # 收敛：ok1 全成功 + bad1 dead_letter + 下游 cancelled → partially_succeeded
        job_row = JobRepository(session).get(tasks[0].job_id)
        assert job_row.status is JobStatus.partially_succeeded, (
            f"Job 应收敛为 partially_succeeded，实际 {job_row.status}"
        )
        # 下游不再 queued（不会永远 running）
        remaining_queued = [t for t in all_tasks if t.status is TaskStatus.queued]
        assert remaining_queued == []


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
