"""每日/维护任务命令（B5/B8；C3 退出口：只提交 durable Job，不绑定执行载体）

设计③「API 只负责提交、查询和控制」——本模块所有 Start* 命令只创建
Job/Task（queued），执行由独立 Python Executor 经 Go Core 调度。
"""

from __future__ import annotations

from typing import Any

from packages.application.commands.jobs import submit_job
from packages.application.commands.task_registry import get_spec


def _submit(
    *,
    kind: str,
    capability: str,
    title: str,
    input_ref: dict[str, Any] | None = None,
) -> dict:
    spec = get_spec(capability)
    return submit_job(
        kind=kind,
        capability=capability,
        title=title,
        input_ref=input_ref or {},
        resource_class=spec.resource_class,
        timeout_s=spec.timeout_s,
        max_attempts=spec.max_attempts,
    )


def start_daily_ingest() -> dict:
    """提交每日抓取+简报任务（MCP 语义），立即返回 task_id"""
    submitted = _submit(
        kind="StartDailyIngest",
        capability="daily_ingest_and_brief",
        title="MCP 触发的每日抓取+简报",
    )
    return {
        "task_id": submitted["task_id"],
        "job_id": submitted["job_id"],
        "status": submitted["status"],
        "message": "用 get_task_status 查进度",
    }


def start_daily_job() -> dict:
    """每日任务（抓取+简报，带阶段进度；jobs 路由语义）"""
    submitted = _submit(
        kind="RunDailyJob",
        capability="daily_ingest_and_brief",
        title="📅 每日任务执行",
    )
    return {
        "task_id": submitted["task_id"],
        "job_id": submitted["job_id"],
        "message": "每日任务已启动",
        "status": submitted["status"],
    }


def start_weekly_graph_maintenance() -> dict:
    """每周图维护（逐主题引用同步 + 增量同步）"""
    submitted = _submit(
        kind="RunCitationSync",
        capability="weekly_graph_maintenance",
        title="🔄 每周图维护",
    )
    return {
        "task_id": submitted["task_id"],
        "job_id": submitted["job_id"],
        "message": "每周图维护已启动",
        "status": submitted["status"],
    }


def start_batch_process_unread(*, max_papers: int = 50) -> dict:
    """批量处理未读论文（embed + skim）——单一 durable Task"""
    submitted = _submit(
        kind="RunBatchProcessUnread",
        capability="batch_process_unread",
        title=f"📚 批量处理未读论文（≤{max_papers} 篇）",
        input_ref={"max_papers": max_papers},
    )
    return {
        "task_id": submitted["task_id"],
        "job_id": submitted["job_id"],
        "message": "批量处理已启动",
        "status": submitted["status"],
    }


def start_daily_report_workflow() -> dict:
    """每日报告完整工作流（精读 + 生成 + 发邮件）"""
    submitted = _submit(
        kind="RunDailyReport",
        capability="daily_report_workflow",
        title="📊 每日报告工作流",
    )
    return {
        "task_id": submitted["task_id"],
        "job_id": submitted["job_id"],
        "message": "每日报告工作流已启动",
        "status": submitted["status"],
    }


def start_daily_report_send_only(*, recipient: str | None = None) -> dict:
    """快速发送模式 — 跳过精读，直接生成简报并发邮件（优先使用缓存）"""
    submitted = _submit(
        kind="RunDailyReportSendOnly",
        capability="daily_report_send_only",
        title="📧 快速发送简报",
        input_ref={"recipient": recipient or ""},
    )
    return {
        "task_id": submitted["task_id"],
        "job_id": submitted["job_id"],
        "message": "快速发送已启动（跳过精读）",
        "status": submitted["status"],
    }


def generate_daily_report_html(*, use_cache: bool = False) -> dict:
    """仅生成简报 HTML — 不发邮件、不精读（同步返回）"""
    from packages.ai.auto_read_service import AutoReadService

    html = AutoReadService().step_generate_html(use_cache=use_cache)
    return {"html": html, "used_cache": use_cache}
