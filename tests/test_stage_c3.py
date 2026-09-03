"""C3：统一旧状态（退出口语义）——submit_job 只入队、Executor 执行、观察面 durable-only

覆盖：submit_job（queued 不执行）、InlineExecutor 执行与 result 存储、失败
dead_letter 收敛、/tasks/{id} durable 解析（id 直查 + external_ref 历史）、
/tasks/active durable-only、GET /jobs 与 /jobs/{id} graph。
"""

from __future__ import annotations

from sqlalchemy import select

from packages.application.commands.jobs import submit_job
from packages.domain.enums import JobStatus, TaskStatus
from packages.storage.db import session_scope
from packages.storage.models import DurableTask, TaskAttempt
from packages.storage.repositories import JobRepository, TaskRepository
from tests.helpers.inline_executor import InlineExecutor


def test_submit_job_only_queues(isolated_db):
    """退出口核心契约：submit_job 不 claim 不执行——任务停在 queued"""
    result = submit_job(
        kind="StartSkim",
        capability="skim_paper",
        title="测试任务",
        input_ref={"paper_id": "p1"},
    )
    assert result["status"] == "queued"
    assert result["created"] is True

    with session_scope() as session:
        task = session.get(DurableTask, result["task_id"])
        assert task.status is TaskStatus.queued
        assert task.lease_token is None  # 未领取
        job = JobRepository(session).get(result["job_id"])
        assert job.status is JobStatus.queued


def test_inline_executor_completes_and_stores_result(isolated_db):
    """InlineExecutor（测试执行器）执行 → succeeded + result_ref 存 Task"""
    result = submit_job(
        kind="TestJob",
        capability="daily_brief_publish",
        title="测试执行",
        input_ref={"recipient": None},
    )
    processed = InlineExecutor(capabilities=["daily_brief_publish"]).run_until_idle()
    assert processed == 1

    with session_scope() as session:
        task = session.get(DurableTask, result["task_id"])
        assert task.status is TaskStatus.succeeded
        assert task.lease_token is None
        attempt = (
            session.execute(select(TaskAttempt).where(TaskAttempt.task_id == task.id))
            .scalars()
            .one()
        )
        assert attempt.executor_id == "inline-exec"
        assert attempt.status.value == "succeeded"
        job = JobRepository(session).get(result["job_id"])
        assert job.status is JobStatus.succeeded


def test_handler_failure_converges_to_dead_letter(isolated_db):
    """handler 抛异常 → fail（max_attempts=1 → dead_letter）+ Job failed"""
    result = submit_job(
        kind="TestJob",
        capability="translate_bilingual_pdf",  # 论文不存在 → 快速失败
        title="失败任务",
        input_ref={"paper_id": "nonexistent", "target_lang": "zh", "mode": "fast"},
        max_attempts=1,
    )
    InlineExecutor(capabilities=["translate_bilingual_pdf"]).run_until_idle()

    with session_scope() as session:
        task = session.get(DurableTask, result["task_id"])
        assert task.status is TaskStatus.dead_letter
        assert task.last_error  # 错误信息被记录
        job = JobRepository(session).get(result["job_id"])
        assert job.status is JobStatus.failed


def test_observation_surface_durable_only(isolated_db):
    """观察面只读 durable：active / unified 视图 / result"""
    from packages.application.queries.tasks import (
        get_task_info,
        get_task_result,
        list_active_tasks,
    )

    result = submit_job(
        kind="TestJob",
        capability="daily_brief_publish",
        title="观察面测试",
        input_ref={"recipient": None},
    )
    task_id = result["task_id"]

    # queued → 在途可见
    active = list_active_tasks()
    assert any(t["task_id"] == task_id for t in active)

    InlineExecutor(capabilities=["daily_brief_publish"]).run_until_idle()

    # 完成 → unified 视图 + 结果
    info = get_task_info(task_id)
    assert info is not None
    assert info["finished"] is True
    assert info["success"] is True
    assert info["task_id"] == task_id  # task_id 即 durable id（不再有 tracker 别名）
    assert isinstance(get_task_result(task_id), dict)

    # 在途列表清空
    assert not any(t["task_id"] == task_id for t in list_active_tasks())


def test_unified_view_resolves_legacy_external_ref(isolated_db):
    """历史行经 external_ref 仍可解析（迁移兼容；新行 task_id 即 durable id）"""
    result = submit_job(
        kind="TestJob",
        capability="daily_brief_publish",
        title="外部引用测试",
        input_ref={"recipient": None},
    )
    with session_scope() as session:
        TaskRepository(session).set_external_ref(result["task_id"], "legacy_tracker_123")

    from packages.application.queries.tasks import get_task_info

    assert get_task_info("legacy_tracker_123") is not None
    assert get_task_info(result["task_id"]) is not None  # id 直查优先


def test_job_graph_endpoint_shape(isolated_db):
    """/jobs/{id} graph：Job + tasks + attempts 三层可观测"""
    from packages.application.queries.jobs import get_job_attempts, get_job_graph

    result = submit_job(
        kind="TestJob",
        capability="daily_brief_publish",
        title="graph 测试",
        input_ref={"recipient": None},
    )
    InlineExecutor(capabilities=["daily_brief_publish"]).run_until_idle()

    with session_scope() as session:
        graph = get_job_graph(session, result["job_id"])
        attempts = get_job_attempts(session, result["job_id"])
    assert graph["status"] == "succeeded"
    assert graph["tasks"][0]["status"] == "succeeded"
    assert attempts and attempts[0]["executor_id"] == "inline-exec"
