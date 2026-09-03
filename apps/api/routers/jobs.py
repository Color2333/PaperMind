"""定时任务 & 行动记录路由
@author Color2333
"""

import logging

from fastapi import APIRouter, HTTPException, Query

from packages.storage.db import session_scope

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/jobs")
def list_durable_jobs(
    status: str | None = Query(default=None),
    kind: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    """durable Job 列表（C3 统一观察面）"""
    from packages.application.queries.jobs import list_jobs as app_list_jobs

    with session_scope() as session:
        return app_list_jobs(session, status=status, kind=kind, limit=limit)


@router.get("/jobs/{job_id}")
def get_durable_job(job_id: str) -> dict:
    """Job graph：Job + 子 Task（含 Attempt 概览）"""
    from packages.application.queries.jobs import get_job_attempts, get_job_graph
    from packages.domain.exceptions import NotFoundError

    with session_scope() as session:
        try:
            graph = get_job_graph(session, job_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        graph["attempts"] = get_job_attempts(session, job_id)
        return graph


@router.post("/jobs/durable")
def submit_durable(body: dict) -> dict:
    """P0 权威提交入口：只写 durable Job/Task（queued），由独立 Executor 经 Go Core 执行。

    body: {kind, capability, title?, input_ref?, idempotency_key?, resource_class?,
           timeout_s?, max_attempts?, payload?}
    """
    from packages.application.commands.jobs import submit_job as app_submit_job
    from packages.domain.exceptions import AppError

    capability = str(body.get("capability") or "")
    kind = str(body.get("kind") or "")
    if not capability or not kind:
        raise HTTPException(status_code=422, detail="kind and capability are required")
    try:
        return app_submit_job(
            kind=kind,
            capability=capability,
            title=str(body.get("title") or ""),
            payload=body.get("payload") or {},
            input_ref=body.get("input_ref") or {},
            idempotency_key=body.get("idempotency_key"),
            resource_class=str(body.get("resource_class") or "default"),
            timeout_s=int(body.get("timeout_s") or 1800),
            max_attempts=int(body.get("max_attempts") or 1),
        )
    except AppError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/jobs/daily/run-once")
def run_daily_once() -> dict:
    """每日任务（抓取+简报）- 后台执行（业务在 application/commands/daily.py）"""
    from packages.application.commands.daily import start_daily_job

    return start_daily_job()


@router.post("/jobs/graph/weekly-run-once")
def run_weekly_graph_once() -> dict:
    """每周图维护任务 - 后台执行"""
    from packages.application.commands.daily import start_weekly_graph_maintenance

    return start_weekly_graph_maintenance()


@router.post("/jobs/batch-process-unread")
def batch_process_unread(
    max_papers: int = Query(default=50, ge=1, le=200),
) -> dict:
    """批量处理未读论文（embed + skim 并行）- 后台执行"""
    from packages.application.commands.daily import start_batch_process_unread

    return start_batch_process_unread(max_papers=max_papers)


# ---------- 行动记录 ----------


@router.get("/actions")
def list_actions(
    action_type: str | None = None,
    topic_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """列出论文入库行动记录"""
    from packages.application.queries.actions import list_actions as app_list_actions

    with session_scope() as session:
        return app_list_actions(
            session, action_type=action_type, topic_id=topic_id, limit=limit, offset=offset
        )


@router.get("/actions/{action_id}")
def get_action_detail(action_id: str) -> dict:
    """获取行动详情"""
    from packages.application.queries.actions import get_action as app_get_action
    from packages.domain.exceptions import NotFoundError

    with session_scope() as session:
        try:
            return app_get_action(session, action_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail="行动记录不存在") from exc


@router.get("/actions/{action_id}/papers")
def get_action_papers(
    action_id: str,
    limit: int = Query(default=200, ge=1, le=500),
) -> dict:
    """获取某次行动关联的论文列表"""
    from packages.application.queries.actions import get_action_papers as app_get_action_papers

    with session_scope() as session:
        return app_get_action_papers(session, action_id, limit=limit)


# ---------- 每日报告任务 ----------


@router.post("/jobs/daily-report/run-once")
async def run_daily_report_once():
    """完整工作流（精读 + 生成 + 发邮件）— 后台执行"""
    from packages.application.commands.daily import start_daily_report_workflow

    return start_daily_report_workflow()


@router.post("/jobs/daily-report/send-only")
async def run_daily_report_send_only(
    recipient: str | None = Query(default=None, description="收件人邮箱（逗号分隔），不填则用配置"),
):
    """快速发送模式 — 跳过精读，直接生成简报并发邮件（优先使用缓存）"""
    from packages.application.commands.daily import start_daily_report_send_only

    return start_daily_report_send_only(recipient=recipient)


@router.post("/jobs/daily-report/generate-only")
def run_daily_report_generate_only(
    use_cache: bool = Query(default=False, description="是否使用缓存"),
):
    """仅生成简报 HTML — 不发邮件、不精读（同步返回）"""
    from packages.application.commands.daily import generate_daily_report_html

    return generate_daily_report_html(use_cache=use_cache)


# ---------- 任务控制（C10）----------


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    """取消 Job：未领取 Task 直接取消，运行中的协作取消"""
    from packages.application.commands.jobs import cancel_job as app_cancel_job

    return app_cancel_job(job_id)


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: str) -> dict:
    """重试 Job：dead_letter/failed Task 重回队列"""
    from packages.application.commands.jobs import retry_job as app_retry_job

    return app_retry_job(job_id)


@router.post("/tasks/{task_id}/retry")
def retry_single_task(task_id: str) -> dict:
    """单 Task 重试（dead_letter 出口）"""
    from packages.application.commands.jobs import retry_task as app_retry_task
    from packages.domain.exceptions import ConflictError

    try:
        return app_retry_task(task_id)
    except ConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/queue/pause")
def pause_queue() -> dict:
    """暂停队列（本进程 claim 停止；跨进程 pause 由 Go Core 接管）"""
    from packages.application.commands.jobs import pause_queue as app_pause_queue

    return app_pause_queue()


@router.post("/queue/resume")
def resume_queue() -> dict:
    """恢复队列"""
    from packages.application.commands.jobs import resume_queue as app_resume_queue

    return app_resume_queue()
