"""
每日/每周定时任务编排 - 智能调度 + 精读限额
@author Color2333
@author Color2333
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
from uuid import UUID

from packages.ai.brief_service import DailyBriefService
from packages.ai.graph_service import GraphService
from packages.ai.pipelines import PaperPipelines
from packages.ai.rate_limiter import acquire_api, get_rate_limiter
from packages.config import get_settings
from packages.domain.enums import ActionType, ReadStatus
from packages.storage.db import session_scope
from packages.storage.models import TopicSubscription
from packages.storage.repositories import (
    PaperRepository,
    TopicRepository,
)

logger = logging.getLogger(__name__)


PAPER_CONCURRENCY = 3


def _process_paper(
    paper_id, force_deep: bool = False, deep_read_quota: Optional[int] = None
) -> dict:
    """
    单篇论文：embed ∥ skim 并行，智能精读

    Args:
        paper_id: 论文 ID
        force_deep: 是否强制精读（忽略配额）
        deep_read_quota: 剩余精读配额（None 表示不限制）

    Returns:
        dict: 处理结果 {skim_score, deep_read, success}
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    settings = get_settings()
    pipelines = PaperPipelines()
    result = {
        "paper_id": str(paper_id)[:8],
        "skim_score": None,
        "deep_read": False,
        "success": False,
        "error": None,
    }

    skim_result = None
    with ThreadPoolExecutor(max_workers=2) as inner:
        fe = inner.submit(pipelines.embed_paper, paper_id)
        fs = inner.submit(pipelines.skim, paper_id)
        for fut in as_completed([fe, fs]):
            try:
                r = fut.result()
                if fut is fs:
                    skim_result = r
            except Exception as exc:
                label = "embed" if fut is fe else "skim"
                logger.warning(
                    "%s %s failed: %s",
                    label,
                    str(paper_id)[:8],
                    exc,
                )
                result["error"] = f"{label}: {exc}"

    # 检查粗读结果
    if skim_result and skim_result.relevance_score is not None:
        result["skim_score"] = skim_result.relevance_score
        result["success"] = True

    # 判断是否精读
    should_deep = False
    deep_reason = ""

    if force_deep:
        should_deep = True
        deep_reason = "强制精读"
    elif skim_result and skim_result.relevance_score >= settings.skim_score_threshold:
        # 检查精读配额
        if deep_read_quota is None or deep_read_quota > 0:
            should_deep = True
            deep_reason = f"高分论文 (分数={skim_result.relevance_score:.2f})"
        else:
            deep_reason = "精读配额已用尽"

    # 执行精读
    if should_deep:
        try:
            # 获取 API 许可
            if acquire_api("llm", timeout=30.0):
                pipelines.deep_dive(UUID(paper_id))
                result["deep_read"] = True
                logger.info("🎯 %s 精读完成 - %s", str(paper_id)[:8], deep_reason)
            else:
                logger.warning("⚠️  %s 等待 API 许可超时，跳过精读", str(paper_id)[:8])
        except Exception as exc:
            logger.warning(
                "deep_dive %s failed: %s",
                str(paper_id)[:8],
                exc,
            )
            result["error"] = f"deep: {exc}"

    return result


def run_topic_ingest(topic_id: str) -> dict:
    """
    单独处理一个主题的抓取 + 处理 - 智能精读限额

    Args:
        topic_id: 主题 ID

    Returns:
        dict: 处理结果统计
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    pipelines = PaperPipelines()
    with session_scope() as session:
        topic = session.get(TopicSubscription, topic_id)
        if not topic:
            return {"topic_id": topic_id, "status": "not_found"}
        topic_name = topic.name

        # 获取精读配额配置
        max_deep_reads = getattr(topic, "max_deep_reads_per_run", 2)

        # 读取日期过滤配置
        enable_date_filter = getattr(topic, "enable_date_filter", False)
        date_filter_days = getattr(topic, "date_filter_days", 7)
        days_back = date_filter_days if enable_date_filter else 0

        last_error: str | None = None
        ids: list[str] = []
        new_count: int = 0
        attempts = 0
        for _attempt in range(topic.retry_limit + 1):
            attempts += 1
            try:
                # 返回详细统计信息
                result = pipelines.ingest_arxiv_with_stats(
                    query=topic.query,
                    max_results=topic.max_results_per_run,
                    topic_id=topic.id,
                    action_type=ActionType.auto_collect,
                    days_back=days_back,
                )
                ids = result["inserted_ids"]
                new_count = result["new_count"]
                last_error = None
                break
            except Exception as exc:
                last_error = str(exc)

        if last_error is not None:
            return {
                "topic_id": topic_id,
                "topic_name": topic_name,
                "status": "failed",
                "attempts": attempts,
                "error": last_error,
                "inserted": 0,
            }

        # 如果没有新论文，直接返回
        if new_count == 0:
            logger.info(
                "⚠️  主题 [%s] 没有新论文（重复 %d 篇），跳过处理",
                topic_name,
                len(ids),
            )
            return {
                "topic_id": topic_id,
                "topic_name": topic_name,
                "status": "no_new_papers",
                "inserted": 0,
                "new_count": 0,
                "total_count": len(ids),
            }

        repo = PaperRepository(session)
        # 只处理这次新入库的论文
        unique = repo.list_by_ids(ids) if ids else []
        # 在 Session 关闭前提取所有需要的数据，避免 DetachedInstanceError
        papers_data = [(str(p.id), p.title) for p in unique]

    logger.info(
        "📝 主题 [%s] 新抓取 %d 篇论文（新论文 %d 篇），精读配额：%d 篇",
        topic_name,
        len(unique),
        new_count,
        max_deep_reads,
    )

    # 第一步：全部论文并行粗读 + 嵌入（不精读）
    logger.info("第一步：并行粗读 + 嵌入...")
    skim_results = []

    with ThreadPoolExecutor(max_workers=PAPER_CONCURRENCY) as pool:
        futs = {
            pool.submit(_process_paper, paper_id, force_deep=False, deep_read_quota=0): paper_id
            for paper_id, _ in papers_data
        }
        for fut in as_completed(futs):
            try:
                result = fut.result()
                skim_results.append(result)
            except Exception as exc:
                paper_id = futs[fut]
                logger.warning(
                    "skim %s failed: %s",
                    str(paper_id)[:8],
                    exc,
                )

    # 第二步：按粗读分数排序，选前 N 篇精读
    logger.info("第二步：选择高分论文进行精读...")
    # 只用 ID 和分数排序，不再引用 ORM 对象
    scored_papers = [
        (r, paper_id)
        for r, (paper_id, _) in zip(skim_results, papers_data)
        if r["success"] and r["skim_score"] is not None
    ]
    scored_papers.sort(key=lambda x: x[0]["skim_score"], reverse=True)

    # 精读前 N 篇
    deep_read_count = 0
    for i, (result, paper_id) in enumerate(scored_papers):
        if deep_read_count >= max_deep_reads:
            logger.info(
                "⚠️  精读配额已用尽 (%d/%d)，剩余 %d 篇跳过精读",
                deep_read_count,
                max_deep_reads,
                len(scored_papers) - i,
            )
            break

        # 只精读分数 >= 阈值的
        if result["skim_score"] < get_settings().skim_score_threshold:
            logger.info("⚠️  %s 分数过低 (%.2f)，跳过精读", str(paper_id)[:8], result["skim_score"])
            continue

        logger.info(
            "🎯 开始精读第 %d 篇：%s (分数=%.2f)",
            deep_read_count + 1,
            str(paper_id)[:50],
            result["skim_score"],
        )

        try:
            # 获取 API 许可
            if acquire_api("llm", timeout=60.0):
                pipelines.deep_dive(UUID(paper_id))  # type: ignore[arg-type]
                deep_read_count += 1
                logger.info("✅ 精读完成 (%d/%d)", deep_read_count, max_deep_reads)
            else:
                logger.warning("等待 API 许可超时，跳过精读")
        except Exception as exc:
            logger.warning(
                "deep_dive %s failed: %s",
                str(paper_id)[:8],
                exc,
            )

    return {
        "topic_id": topic_id,
        "topic_name": topic_name,
        "status": "ok",
        "attempts": attempts,
        "inserted": len(ids),
        "skimmed": len(skim_results),
        "deep_read": deep_read_count,
        "max_deep_reads": max_deep_reads,
    }


def run_daily_ingest() -> dict:
    """兼容旧调用：遍历所有 enabled 主题执行抓取"""
    with session_scope() as session:
        topic_repo = TopicRepository(session)
        topics = topic_repo.list_topics(enabled_only=True)
        if not topics:
            topics = [
                topic_repo.upsert_topic(
                    name="default-ml",
                    query="cat:cs.LG OR cat:cs.CL",
                    enabled=True,
                    max_results_per_run=20,
                    retry_limit=2,
                )
            ]
        topic_ids = [t.id for t in topics]

    results = []
    for tid in topic_ids:
        results.append(run_topic_ingest(tid))

    total_inserted = sum(r.get("inserted", 0) for r in results)
    total_processed = sum(r.get("processed", 0) for r in results)
    return {
        "newly_inserted": total_inserted,
        "processed": total_processed,
        "topics": results,
    }


def run_daily_brief() -> dict:
    settings = get_settings()
    return DailyBriefService().publish(recipient=settings.notify_default_to)


def run_weekly_graph_maintenance() -> dict:
    with session_scope() as session:
        topics = TopicRepository(session).list_topics(enabled_only=True)
    graph = GraphService()
    topic_results = []
    for t in topics:
        try:
            topic_results.append(
                graph.sync_citations_for_topic(
                    topic_id=t.id,
                    paper_limit=20,
                    edge_limit_per_paper=6,
                )
            )
        except Exception:
            logger.exception(
                "Failed to sync citations for topic %s",
                t.id,
            )
            continue
    incremental = graph.sync_incremental(paper_limit=50, edge_limit_per_paper=6)
    return {
        "topic_sync": topic_results,
        "incremental": incremental,
    }
