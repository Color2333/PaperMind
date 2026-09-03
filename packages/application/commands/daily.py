"""每日/维护任务命令（B5/B8，设计② StartDailyIngest / RunDailyJob / StartBatchProcess 等）

tracker 提交与后台线程为过渡执行载体（C3 起统一收敛为 durable Job；
BackgroundTasks 原语在此层消失——命令自管线程，router 不再决定执行载体）。
"""

from __future__ import annotations

import logging
import threading
import uuid as _uuid

from packages.application.commands.jobs import submit_tracked_compat

logger = logging.getLogger(__name__)


def start_daily_ingest() -> dict:
    """提交每日抓取+简报任务（MCP 语义），立即返回 task_id"""

    def _run_daily(progress_callback=None):
        from packages.ai.daily_runner import run_daily_brief, run_daily_ingest

        ingest = run_daily_ingest()
        brief = run_daily_brief()
        return {"ingest": ingest, "brief": brief}

    task_id = submit_tracked_compat(
        task_type="mcp_daily",
        title="MCP 触发的每日抓取+简报",
        fn=_run_daily,
        total=2,
        category="mcp",
        kind="StartDailyIngest",
        capability="run_daily_ingest",
    )
    return {"task_id": task_id, "status": "started", "message": "用 get_task_status 查进度"}


def start_daily_job() -> dict:
    """每日任务（抓取+简报，带阶段进度；jobs 路由语义）"""
    from packages.ai.daily_runner import run_daily_brief, run_daily_ingest

    def _fn(progress_callback=None):
        if progress_callback:
            progress_callback("正在执行订阅收集...", 10, 100)
        ingest = run_daily_ingest()
        if progress_callback:
            progress_callback("正在生成每日简报...", 70, 100)
        brief = run_daily_brief()
        return {"ingest": ingest, "brief": brief}

    task_id = submit_tracked_compat(
        "daily_job",
        "📅 每日任务执行",
        _fn,
        category="report",
        kind="RunDailyJob",
        capability="run_daily_job",
    )
    return {"task_id": task_id, "message": "每日任务已启动", "status": "running"}


def start_weekly_graph_maintenance() -> dict:
    """每周图维护（逐主题引用同步 + 增量同步）"""
    from packages.application.queries.graph import _graph_service
    from packages.storage.db import session_scope
    from packages.storage.repositories import TopicRepository

    def _fn(progress_callback=None):
        if progress_callback:
            progress_callback("正在获取主题列表...", 10, 100)

        with session_scope() as session:
            topics = TopicRepository(session).list_topics(enabled_only=True)

        total_topics = len(topics)
        graph = _graph_service()
        topic_results = []

        for i, t in enumerate(topics):
            if progress_callback:
                progress_callback(
                    f"处理主题 {i + 1}/{total_topics}: {t.name[:20]}...",
                    20 + int((i + 1) / total_topics * 40),
                    100,
                )
            try:
                topic_results.append(
                    graph.sync_citations_for_topic(
                        topic_id=t.id,
                        paper_limit=20,
                        edge_limit_per_paper=6,
                    )
                )
            except Exception:
                logger.exception("Failed to sync citations for topic %s", t.id)
                continue

        if progress_callback:
            progress_callback("正在执行增量同步...", 70, 100)
        incremental = graph.sync_incremental(paper_limit=50, edge_limit_per_paper=6)

        if progress_callback:
            progress_callback("图维护完成", 95, 100)
        return {
            "topic_sync": topic_results,
            "incremental": incremental,
        }

    task_id = submit_tracked_compat(
        "weekly_maintenance",
        "🔄 每周图维护",
        _fn,
        category="sync",
        kind="RunCitationSync",
        capability="run_weekly_maintenance",
    )
    return {"task_id": task_id, "message": "每周图维护已启动", "status": "running"}


def start_batch_process_unread(*, max_papers: int = 50) -> dict:
    """批量处理未读论文（embed + skim 并行）— 命令自管后台线程"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from packages.ai.daily_runner import PAPER_CONCURRENCY, _process_paper
    from packages.domain.enums import ReadStatus
    from packages.domain.task_tracker import global_tracker
    from packages.storage.db import session_scope
    from packages.storage.repositories import PaperRepository

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

    task_id = f"batch_unread_{_uuid.uuid4().hex[:8]}"

    def _run_batch():
        processed = 0
        failed = 0
        try:
            global_tracker.start(
                task_id,
                "batch_process",
                f"📚 批量处理未读论文 ({total} 篇)",
                total=total,
                category="analysis",
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
            logger.info("批量处理完成: %d 成功, %d 失败", processed, failed)
        except Exception as e:
            global_tracker.finish(task_id, success=False, error=str(e))
            logger.error("批量处理失败: %s", e, exc_info=True)

    threading.Thread(target=_run_batch, daemon=True, name="batch-unread").start()
    return {"task_id": task_id, "message": f"批量处理已启动 ({total} 篇论文)", "status": "running"}


def start_daily_report_workflow() -> dict:
    """每日报告完整工作流（精读 + 生成 + 发邮件）— 命令自管后台线程"""
    import asyncio

    from packages.ai.auto_read_service import AutoReadService
    from packages.domain.task_tracker import global_tracker

    def _run_workflow_bg():
        task_id = f"daily_report_{_uuid.uuid4().hex[:8]}"
        global_tracker.start(
            task_id, "daily_report", "📊 每日报告工作流", total=100, category="report"
        )

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
            logger.error("每日报告工作流失败: %s", e, exc_info=True)

    threading.Thread(target=_run_workflow_bg, daemon=True, name="daily-report").start()
    return {"message": "每日报告工作流已启动", "status": "running"}


def start_daily_report_send_only(*, recipient: str | None = None) -> dict:
    """快速发送模式 — 跳过精读，直接生成简报并发邮件（优先使用缓存）"""
    from packages.ai.auto_read_service import AutoReadService
    from packages.domain.task_tracker import global_tracker

    def _run_send_only_bg():
        task_id = f"report_send_{_uuid.uuid4().hex[:8]}"
        global_tracker.start(
            task_id, "report_send", "📧 快速发送简报", total=100, category="report"
        )

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
            logger.error("快速发送失败: %s", e, exc_info=True)

    threading.Thread(target=_run_send_only_bg, daemon=True, name="report-send").start()
    return {"message": "快速发送已启动（跳过精读）", "status": "running"}


def generate_daily_report_html(*, use_cache: bool = False) -> dict:
    """仅生成简报 HTML — 不发邮件、不精读（同步返回）"""
    from packages.ai.auto_read_service import AutoReadService

    html = AutoReadService().step_generate_html(use_cache=use_cache)
    return {"html": html, "used_cache": use_cache}
