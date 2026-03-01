"""定时任务 & 行动记录路由
@author Color2333
"""

import logging
import uuid as _uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query

from apps.api.deps import pipelines
from packages.ai.daily_runner import run_daily_brief, run_daily_ingest, run_weekly_graph_maintenance
from packages.domain.enums import ReadStatus
from packages.domain.task_tracker import global_tracker
from packages.storage.db import session_scope
from packages.storage.repositories import PaperRepository

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/jobs/daily/run-once")
def run_daily_once() -> dict:
    """每日任务（抓取+简报）- 后台执行"""

    def _fn(progress_callback=None):
        if progress_callback:
            progress_callback("正在执行订阅收集...", 10, 100)
        ingest = run_daily_ingest()
        if progress_callback:
            progress_callback("正在生成每日简报...", 70, 100)
        brief = run_daily_brief()
        return {"ingest": ingest, "brief": brief}

    task_id = global_tracker.submit("daily_job", "📅 每日任务执行", _fn)
    return {"task_id": task_id, "message": "每日任务已启动", "status": "running"}


@router.post("/jobs/graph/weekly-run-once")
def run_weekly_graph_once() -> dict:
    """每周图维护任务 - 后台执行"""

    def _fn(progress_callback=None):
        return run_weekly_graph_maintenance()

    task_id = global_tracker.submit("weekly_maintenance", "🔄 每周图维护", _fn)
    return {"task_id": task_id, "message": "每周图维护已启动", "status": "running"}


@router.post("/jobs/batch-process-unread")
def batch_process_unread(
    background_tasks: BackgroundTasks,
    max_papers: int = Query(default=50, ge=1, le=200),
) -> dict:
    """批量处理未读论文（embed + skim 并行）- 后台执行"""
    import uuid
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from packages.ai.daily_runner import _process_paper, PAPER_CONCURRENCY

    # 先获取需要处理的论文数量
    with session_scope() as session:
        repo = PaperRepository(session)
        unread = repo.list_by_read_status(ReadStatus.unread, limit=max_papers)
        target_ids = []
        for p in unread:
            needs_embed = p.embedding is None
            needs_skim = p.read_status == ReadStatus.unread
            if needs_embed or needs_skim:
                target_ids.append(p.id)

    total = len(target_ids)
    if total == 0:
        return {"processed": 0, "total_unread": 0, "message": "没有需要处理的未读论文"}

    task_id = f"batch_unread_{uuid.uuid4().hex[:8]}"

    def _run_batch():
        processed = 0
        failed = 0
        try:
            global_tracker.start(
                task_id, "batch_process", f"📚 批量处理未读论文 ({total} 篇)", total=total
            )

            with ThreadPoolExecutor(max_workers=PAPER_CONCURRENCY) as pool:
                futs = {pool.submit(_process_paper, pid): pid for pid in target_ids}
                for fut in as_completed(futs):
                    try:
                        fut.result()
                        processed += 1
                        global_tracker.update(
                            task_id, processed, f"正在处理... ({processed}/{total})", total=total
                        )
                    except Exception as exc:
                        failed += 1
                        logger.warning("batch process %s failed: %s", str(futs[fut])[:8], exc)

            global_tracker.finish(task_id, success=True)
            logger.info(f"批量处理完成: {processed} 成功, {failed} 失败")
        except Exception as e:
            global_tracker.finish(task_id, success=False, error=str(e))
            logger.error(f"批量处理失败: {e}", exc_info=True)

    background_tasks.add_task(_run_batch)
    return {"task_id": task_id, "message": f"批量处理已启动 ({total} 篇论文)", "status": "running"}


# ---------- 行动记录 ----------


@router.get("/actions")
def list_actions(
    action_type: str | None = None,
    topic_id: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """列出论文入库行动记录"""
    from packages.storage.repositories import ActionRepository

    with session_scope() as session:
        repo = ActionRepository(session)
        actions, total = repo.list_actions(
            action_type=action_type,
            topic_id=topic_id,
            limit=limit,
            offset=offset,
        )
        return {
            "items": [
                {
                    "id": a.id,
                    "action_type": a.action_type,
                    "title": a.title,
                    "query": a.query,
                    "topic_id": a.topic_id,
                    "paper_count": a.paper_count,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                }
                for a in actions
            ],
            "total": total,
        }


@router.get("/actions/{action_id}")
def get_action_detail(action_id: str) -> dict:
    """获取行动详情"""
    from packages.storage.repositories import ActionRepository

    with session_scope() as session:
        repo = ActionRepository(session)
        action = repo.get_action(action_id)
        if not action:
            raise HTTPException(status_code=404, detail="行动记录不存在")
        return {
            "id": action.id,
            "action_type": action.action_type,
            "title": action.title,
            "query": action.query,
            "topic_id": action.topic_id,
            "paper_count": action.paper_count,
            "created_at": action.created_at.isoformat() if action.created_at else None,
        }


@router.get("/actions/{action_id}/papers")
def get_action_papers(
    action_id: str,
    limit: int = Query(default=200, ge=1, le=500),
) -> dict:
    """获取某次行动关联的论文列表"""
    from packages.storage.repositories import ActionRepository

    with session_scope() as session:
        repo = ActionRepository(session)
        papers = repo.get_papers_by_action(action_id, limit=limit)
        return {
            "action_id": action_id,
            "items": [
                {
                    "id": p.id,
                    "title": p.title,
                    "arxiv_id": p.arxiv_id,
                    "publication_date": p.publication_date.isoformat()
                    if p.publication_date
                    else None,
                    "read_status": p.read_status,
                }
                for p in papers
            ],
        }


# ---------- 每日报告任务 ----------


@router.post("/jobs/daily-report/run-once")
async def run_daily_report_once(background_tasks: BackgroundTasks):
    """完整工作流（精读 + 生成 + 发邮件）— 后台执行"""
    import asyncio
    from packages.ai.auto_read_service import AutoReadService

    def _run_workflow_bg():
        task_id = f"daily_report_{_uuid.uuid4().hex[:8]}"
        global_tracker.start(task_id, "daily_report", "📊 每日报告工作流", total=100)

        def _progress(msg: str, cur: int, tot: int):
            global_tracker.update(task_id, cur, msg, total=100)

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(AutoReadService().run_daily_workflow(_progress))
            if result.get("success"):
                global_tracker.finish(task_id, success=True)
            else:
                global_tracker.finish(task_id, success=False, error=result.get("error", "未知错误"))
        except Exception as e:
            global_tracker.finish(task_id, success=False, error=str(e))
            logger.error(f"每日报告工作流失败: {e}", exc_info=True)

    background_tasks.add_task(_run_workflow_bg)
    return {"message": "每日报告工作流已启动", "status": "running"}


@router.post("/jobs/daily-report/send-only")
async def run_daily_report_send_only(
    background_tasks: BackgroundTasks,
    recipient: str | None = Query(default=None, description="收件人邮箱（逗号分隔），不填则用配置"),
):
    """快速发送模式 — 跳过精读，直接生成简报并发邮件（优先使用缓存）"""
    from packages.ai.auto_read_service import AutoReadService

    def _run_send_only_bg():
        task_id = f"report_send_{_uuid.uuid4().hex[:8]}"
        global_tracker.start(task_id, "report_send", "📧 快速发送简报", total=100)

        def _progress(msg: str, cur: int, tot: int):
            global_tracker.update(task_id, cur, msg, total=100)

        try:
            recipients = (
                [e.strip() for e in recipient.split(",") if e.strip()] if recipient else None
            )
            result = AutoReadService().send_only(recipients, _progress)
            if result.get("success"):
                global_tracker.finish(task_id, success=True)
            else:
                global_tracker.finish(task_id, success=False, error=result.get("error", "未知错误"))
        except Exception as e:
            global_tracker.finish(task_id, success=False, error=str(e))
            logger.error(f"快速发送失败: {e}", exc_info=True)

    background_tasks.add_task(_run_send_only_bg)
    return {"message": "快速发送已启动（跳过精读）", "status": "running"}


@router.post("/jobs/daily-report/generate-only")
def run_daily_report_generate_only(
    use_cache: bool = Query(default=False, description="是否使用缓存"),
):
    """仅生成简报 HTML — 不发邮件、不精读（同步返回）"""
    from packages.ai.auto_read_service import AutoReadService

    html = AutoReadService().step_generate_html(use_cache=use_cache)
    return {"html": html, "used_cache": use_cache}
