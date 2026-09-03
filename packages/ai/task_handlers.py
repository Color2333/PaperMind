"""durable Task handler 集合（C3 退出门：全部长任务的唯一执行体）

约定：每个 handler 是模块级函数，签名 `fn(*, progress=None, **input_keys)`；
- `progress(msg, current, total)` 由 Executor 注入（经 Go Core 协议上报，
  同时续约 lease——executor 不直写任务状态）；
- `cancel_check`（如 handler 接受）在安全检查点探测协作取消，置位时抛
  `TaskCancelledError`；
- handler 不捕获任务级异常（失败交给 durable store 的重试/dead_letter 语义）；
- 重试退避由 Task 层负责，handler 内不再自做 retry。

C4 注册表（TASK_CAPABILITIES）的 handler dotted path 全部指向本模块或既有
服务类方法；调用点不得再绑定闭包。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from packages.executor_runtime.runner import TaskCancelledError

logger = logging.getLogger(__name__)

ProgressFn = Callable[[str, int, int], None] | None


def _checked(cancel_check: Callable[[], bool] | None) -> None:
    """安全检查点：协作取消置位则抛 TaskCancelledError"""
    if cancel_check is not None and cancel_check():
        raise TaskCancelledError("协作取消（handler 安全点）")


# ---------- 每日/维护 ----------


def daily_ingest_and_brief(*, progress: ProgressFn = None, **_: Any) -> dict:
    """每日抓取 + 简报（StartDailyIngest / RunDailyJob 共用）"""
    from packages.ai.daily_runner import run_daily_brief, run_daily_ingest

    if progress:
        progress("正在执行订阅收集...", 10, 100)
    ingest = run_daily_ingest()
    if progress:
        progress("正在生成每日简报...", 70, 100)
    brief = run_daily_brief()
    if progress:
        progress("每日任务完成", 100, 100)
    return {"ingest": ingest, "brief": brief}


def weekly_graph_maintenance(*, progress: ProgressFn = None, **_: Any) -> dict:
    """每周图维护（逐主题引用同步 + 增量同步）"""
    from packages.application.queries.graph import _graph_service
    from packages.storage.db import session_scope
    from packages.storage.repositories import TopicRepository

    if progress:
        progress("正在获取主题列表...", 10, 100)
    with session_scope() as session:
        topics = TopicRepository(session).list_topics(enabled_only=True)

    total_topics = len(topics)
    graph = _graph_service()
    topic_results: list[dict] = []
    for i, t in enumerate(topics):
        if progress:
            progress(
                f"处理主题 {i + 1}/{total_topics}: {t.name[:20]}...",
                20 + int((i + 1) / total_topics * 40),
                100,
            )
        try:
            topic_results.append(
                graph.sync_citations_for_topic(
                    topic_id=t.id, paper_limit=20, edge_limit_per_paper=6
                )
            )
        except Exception:
            logger.exception("Failed to sync citations for topic %s", t.id)
            continue

    if progress:
        progress("正在执行增量同步...", 70, 100)
    incremental = graph.sync_incremental(paper_limit=50, edge_limit_per_paper=6)
    if progress:
        progress("图维护完成", 95, 100)
    return {"topic_sync": topic_results, "incremental": incremental}


def daily_report_workflow(*, progress: ProgressFn = None, **_: Any) -> dict:
    """每日报告完整工作流（精读 + 生成 + 发邮件）"""
    from packages.ai.auto_read_service import AutoReadService

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(AutoReadService().run_daily_workflow(progress))
    finally:
        loop.close()


def daily_report_send_only(
    *, recipient: str | None = None, progress: ProgressFn = None, **_: Any
) -> dict:
    """快速发送模式（跳过精读，直接生成简报并发邮件）"""
    from packages.ai.auto_read_service import AutoReadService

    recipients = [e.strip() for e in recipient.split(",") if e.strip()] if recipient else None
    return AutoReadService().send_only(recipients, progress)


def batch_process_unread(
    *,
    max_papers: int = 50,
    progress: ProgressFn = None,
    cancel_check: Callable[[], bool] | None = None,
    **_: Any,
) -> dict:
    """批量处理未读论文（embed + skim，受控并发）"""
    from packages.ai.daily_runner import PAPER_CONCURRENCY, _process_paper
    from packages.domain.enums import ReadStatus
    from packages.storage.db import session_scope
    from packages.storage.repositories import PaperRepository

    with session_scope() as session:
        repo = PaperRepository(session)
        unread = repo.list_by_read_status(ReadStatus.unread, limit=max_papers)
        target_ids = [
            p.id for p in unread if p.embedding is None or p.read_status == ReadStatus.unread
        ]

    total = len(target_ids)
    if total == 0:
        return {"processed": 0, "failed": 0, "total": 0, "message": "没有需要处理的未读论文"}

    processed = failed = 0
    with ThreadPoolExecutor(max_workers=PAPER_CONCURRENCY) as pool:
        futures = {pool.submit(_process_paper, pid): pid for pid in target_ids}
        for fut in as_completed(futures):
            _checked(cancel_check)
            try:
                fut.result()
                processed += 1
            except Exception as exc:
                failed += 1
                logger.warning("batch process %s failed: %s", str(futures[fut])[:8], exc)
            if progress:
                progress(f"正在处理... ({processed + failed}/{total})", processed + failed, total)

    return {"processed": processed, "failed": failed, "total": total}


def skim_papers_batch(
    *,
    paper_ids: list[str],
    progress: ProgressFn = None,
    cancel_check: Callable[[], bool] | None = None,
    **_: Any,
) -> dict:
    """对选定论文批量粗读（前端批量按钮的单一任务化入口）"""
    from packages.ai.pipelines import PaperPipelines

    pipelines = PaperPipelines()
    total = len(paper_ids)
    ok, failed = 0, 0
    for i, pid in enumerate(paper_ids, 1):
        _checked(cancel_check)
        if progress:
            progress(f"粗读中 {i}/{total}", i, total)
        try:
            pipelines.skim(pid)
            ok += 1
        except Exception as exc:
            failed += 1
            logger.warning("batch skim %s failed: %s", str(pid)[:8], exc)
    return {"skimmed": ok, "failed": failed, "total": total}


# ---------- 抓取/入库 ----------


def topic_dispatch(*, progress: ProgressFn = None, **_: Any) -> dict:
    """主题调度触发（每小时）：按订阅计划逐主题抓取（自 apps/worker 迁入）"""
    from datetime import UTC, datetime

    from packages.ai.daily_runner import run_topic_ingest
    from packages.ai.idle_processor import set_dispatching
    from packages.storage.db import session_scope
    from packages.storage.repositories import TopicRepository

    def _should_run(freq: str, time_utc: int, hour: int, weekday: int) -> bool:
        if freq == "hourly":
            return True
        if freq == "twice_daily":
            return hour in (time_utc, (time_utc + 12) % 24)
        if freq == "weekdays":
            return weekday < 5 and hour == time_utc
        if freq == "weekly":
            return weekday == 0 and hour == time_utc
        return hour == time_utc  # daily

    now = datetime.now(UTC)
    hour, weekday = now.hour, now.weekday()
    with session_scope() as session:
        topics = TopicRepository(session).list_topics(enabled_only=True)
        candidates = [
            {"id": t.id, "name": t.name}
            for t in topics
            if _should_run(
                getattr(t, "schedule_frequency", "daily"),
                getattr(t, "schedule_time_utc", 21),
                hour,
                weekday,
            )
        ]
    if not candidates:
        return {"triggered": 0, "failed": []}

    if progress:
        progress(f"触发 {len(candidates)} 个主题抓取", 10, 100)
    set_dispatching(True)
    failures: list[str] = []
    try:
        for i, c in enumerate(candidates):
            if progress:
                progress(
                    f"主题 {c['name'][:20]} ({i + 1}/{len(candidates)})",
                    10 + int(i / len(candidates) * 80),
                    100,
                )
            try:
                run_topic_ingest(c["id"])
            except Exception as exc:
                logger.exception("topic_dispatch failed for %s", c["name"])
                failures.append(f"{c['name']}: {exc}")
    finally:
        set_dispatching(False)
    return {"triggered": len(candidates), "failed": failures}


def cs_feed_dispatch(*, progress: ProgressFn = None, **_: Any) -> dict:
    """CS 分类订阅调度（每小时）：同步分类 + 抓取订阅"""
    from packages.ai.cs_feed_orchestrator import CSFeedOrchestrator

    if progress:
        progress("同步 CS 分类...", 10, 100)
    orchestrator = CSFeedOrchestrator()
    orchestrator.sync_categories()
    if progress:
        progress("抓取订阅分类...", 50, 100)
    orchestrator.run()
    return {"status": "done"}


def fetch_topic_papers(*, topic_id: str, progress: ProgressFn = None, **_: Any) -> dict:
    """手动触发单个订阅抓取（分阶段进度：抓取 0-50% → 处理 50-100%）"""
    from packages.ai.daily_runner import run_topic_ingest

    def _stage(msg, cur, tot):
        if progress:
            progress(f"抓取：{msg}", int(cur / tot * 50) if tot else 0, 100)

    result = run_topic_ingest(topic_id, progress_callback=_stage)
    if progress:
        progress("处理完成", 100, 100)
    return result


def ingest_arxiv_query(
    *,
    query: str,
    max_results: int = 20,
    topic_id: str | None = None,
    sort_by: str = "submittedDate",
    days_back: int = 7,
    progress: ProgressFn = None,
    **_: Any,
) -> dict:
    """按关键词从 arXiv 搜索并入库（/ingest/arxiv 的任务化入口）"""
    from packages.application.commands.ingest import import_from_arxiv_query

    total, inserted, _new = import_from_arxiv_query(
        query=query,
        max_results=max_results,
        topic_id=topic_id,
        sort_by=sort_by,
        days_back=days_back,
        progress=progress,
    )
    return {"total": total, "inserted_ids": inserted[:20]}


def import_selected(
    *, arxiv_ids: list[str], query: str, progress: ProgressFn = None, **_: Any
) -> dict:
    """按选中 ID 从 arXiv 入库（agent/HTTP 共用）"""
    from packages.application.commands.ingest import import_selected_papers

    return import_selected_papers(arxiv_ids=arxiv_ids, query=query, progress=progress)


def import_references(
    *,
    source_paper_id: str,
    source_paper_title: str,
    entries: list[dict],
    topic_ids: list[str] | None = None,
    progress: ProgressFn = None,
    **_: Any,
) -> dict:
    """一键导入参考文献"""
    from packages.ai.pipelines.reference_import import ReferenceImporter

    return ReferenceImporter()._run_import(  # noqa: SLF001 — handler 即执行体
        source_paper_id=source_paper_id,
        source_paper_title=source_paper_title,
        entries=entries,
        topic_ids=topic_ids or [],
        progress_callback=progress,
    )


def cs_feed_fetch_category(*, category_code: str, progress: ProgressFn = None, **_: Any) -> dict:
    """抓取单个 CS 分类（自 cs_feeds 命令迁入）"""
    from packages.application.commands.cs_feeds import _fetch_category_impl

    return _fetch_category_impl(category_code=category_code, progress=progress)


# ---------- Workflow 可执行 handler（第三轮 REVIEW：注册表任务须可被独立 Executor 执行）----------


def upsert_paper_data(
    *,
    arxiv_id: str,
    title: str = "",
    abstract: str = "",
    metadata: dict | None = None,
    progress: ProgressFn = None,
    **_: Any,
) -> dict:
    """按元数据 upsert 论文（RunTopicResearch fan-out 的 upsert 节点）。

    返回 {paper_id}——下游节点经输出绑定（${node:paper_id}）引用。
    """
    from packages.domain.schemas import PaperCreate
    from packages.storage.db import session_scope
    from packages.storage.repositories import PaperRepository

    with session_scope() as session:
        paper = PaperRepository(session).upsert_paper(
            PaperCreate(
                arxiv_id=arxiv_id,
                title=title or f"arXiv:{arxiv_id}",
                abstract=abstract or "",
                metadata=metadata or {},
            )
        )
        return {"paper_id": str(paper.id), "arxiv_id": arxiv_id}


def download_source_data(*, arxiv_id: str, progress: ProgressFn = None, **_: Any) -> dict:
    """按 arXiv ID 下载 PDF 并回填 paper.pdf_path（download_source 节点）"""
    from packages.integrations.arxiv_client import ArxivClient
    from packages.storage.db import session_scope
    from packages.storage.repositories import PaperRepository

    pdf_path = ArxivClient().download_pdf(arxiv_id)
    with session_scope() as session:
        repo = PaperRepository(session)
        paper = repo.get_by_arxiv(arxiv_id)
        if paper is None:
            raise ValueError(f"论文 {arxiv_id} 不在库中（upsert 应先行）")
        repo.set_pdf_path(paper.id, pdf_path)
        return {"paper_id": str(paper.id), "pdf_path": pdf_path}


def send_brief_email_effect(
    *,
    recipient: str,
    subject: str = "PaperMind 每日简报",
    content_id: str = "",
    progress: ProgressFn = None,
    **_: Any,
) -> dict:
    """发送简报邮件（BuildDailyBrief 的 send 节点）——effect ledger 保护的唯一发送路径。

    幂等语义（第三轮 REVIEW P1）：发送前查账本，已登记则跳过；
    "先登记后发送崩溃会漏发"窗口以 manual_recovery 兜底（发送异常时账本
    不登记，Task 进 manual_recovery 由人工重放——人工重放时账本挡重复）。
    """
    from packages.application.commands.effect_ledger import has_effect, register_effect
    from packages.storage.db import session_scope

    effect_key = f"brief_mail:{recipient}:{content_id or subject}"
    with session_scope() as session:
        if has_effect(session, effect_key):
            return {"sent": False, "skipped": True, "effect_key": effect_key}

    from packages.storage.db import session_scope as _scope
    from packages.storage.repositories import GeneratedContentRepository

    html = ""
    if content_id:
        with _scope() as session:
            content = GeneratedContentRepository(session).get(content_id)
            html = content.markdown or ""
    from packages.integrations.notifier import NotificationService

    NotificationService().send_email_html(recipient=recipient, subject=subject, html=html)
    with session_scope() as session:
        register_effect(session, effect_key=effect_key, kind="email")
    return {"sent": True, "effect_key": effect_key}


# ---------- 引用图谱 / 生成 ----------


def sync_citations_incremental(
    *, paper_limit: int = 40, edge_limit_per_paper: int = 6, progress: ProgressFn = None, **_: Any
) -> dict:
    """增量引用同步"""
    from packages.application.queries.graph import _graph_service

    if progress:
        progress("正在同步增量引用...", 20, 100)
    result = _graph_service().sync_incremental(
        paper_limit=paper_limit, edge_limit_per_paper=edge_limit_per_paper
    )
    if progress:
        progress("增量引用同步完成", 90, 100)
    return result


def sync_citations_topic(
    *,
    topic_id: str,
    paper_limit: int = 30,
    edge_limit_per_paper: int = 6,
    progress: ProgressFn = None,
    **_: Any,
) -> dict:
    """主题引用同步"""
    from packages.application.queries.graph import _graph_service

    if progress:
        progress("正在同步主题引用...", 20, 100)
    result = _graph_service().sync_citations_for_topic(
        topic_id=topic_id, paper_limit=paper_limit, edge_limit_per_paper=edge_limit_per_paper
    )
    if progress:
        progress("主题引用同步完成", 90, 100)
    return result


def topic_wiki_save(
    *, keyword: str, limit: int = 120, progress: ProgressFn = None, **_: Any
) -> dict:
    """主题 Wiki 生成并写入 generated_contents（HTTP 语义）"""
    from packages.application.commands.generated import save_generated_content
    from packages.application.commands.graph import get_topic_wiki
    from packages.storage.db import session_scope

    def _adapted(pct: float, msg: str):
        if progress:
            progress(msg, int(pct * 100), 100)

    result = get_topic_wiki(keyword=keyword, limit=limit, progress_callback=_adapted)
    with session_scope() as session:
        result["content_id"] = save_generated_content(
            session,
            content_type="topic_wiki",
            title=f"Topic Wiki: {keyword}",
            markdown=result.get("markdown", ""),
            keyword=keyword,
            metadata_json={k: v for k, v in result.items() if k != "markdown"},
        )
    return result


def daily_brief_publish(
    *, recipient: str | None = None, progress: ProgressFn = None, **_: Any
) -> dict:
    """每日简报（HTTP 语义：DailyBriefService.publish，返回含 content_id）"""
    from packages.ai.brief_service import DailyBriefService

    if progress:
        progress("正在生成每日简报...", 20, 100)
    result = DailyBriefService().publish(recipient=recipient)
    if progress:
        progress("简报生成完成", 95, 100)
    return result


# ---------- 分析 / 翻译 ----------


def analyze_figures(
    *, paper_id: str, max_figures: int = 12, progress: ProgressFn = None, **_: Any
) -> dict:
    """论文图表分析（自 papers 命令迁入）"""
    from packages.ai.analysis_service import FigureService
    from packages.storage.db import session_scope
    from packages.storage.repositories import PaperRepository

    pid = paper_id
    with session_scope() as session:
        paper = PaperRepository(session).get_by_id(pid)
        pdf_path = paper.pdf_path
        paper_title = (paper.title or pid[:8])[:30]

    if progress:
        progress("正在提取图表...", 10, 100)
    results = FigureService().analyze_paper_figures(pid, pdf_path, max_figures)

    total_figures = len(results)
    if progress and total_figures > 0:
        progress(f"正在生成解读 ({total_figures} 个图表)...", 50, 100)

    items = FigureService.get_paper_analyses(pid)
    for i, item in enumerate(items):
        if item.get("has_image"):
            item["image_url"] = f"/papers/{pid}/figures/{item['id']}/image"
        else:
            item["image_url"] = None
        if progress:
            progress(
                f"解读中 ({i + 1}/{total_figures})...", 50 + int((i + 1) / total_figures * 45), 100
            )

    if progress:
        progress("图表分析完成", 95, 100)
    return {"paper_id": str(pid), "count": len(items), "items": items, "title": paper_title}


def translate_bilingual_pdf(
    *,
    paper_id: str,
    target_lang: str = "zh",
    mode: str = "fast",
    progress: ProgressFn = None,
    **_: Any,
) -> dict:
    """双语 PDF 翻译（fast=分段对照 / layout=pdf2zh 排版保留）"""
    from packages.ai.services.bilingual_pdf import (
        process_fast_translation,
        process_layout_translation,
    )
    from packages.storage.db import session_scope
    from packages.storage.repositories import PaperRepository

    with session_scope() as session:
        paper = PaperRepository(session).get_by_id(paper_id)
        pdf_path = paper.pdf_path
    if not pdf_path:
        raise ValueError(f"论文 {paper_id[:8]} 没有 PDF 文件")

    fn = process_fast_translation if mode == "fast" else process_layout_translation
    return fn(paper_id, pdf_path, target_lang, progress_callback=progress)
