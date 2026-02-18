"""
每日/每周定时任务编排
@author Bamzc
"""
from __future__ import annotations

import logging

from packages.ai.brief_service import DailyBriefService
from packages.ai.graph_service import GraphService
from packages.ai.pipelines import PaperPipelines
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


def _process_paper(paper_id) -> None:
    """单篇论文：embed ∥ skim 并行，按需精读"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    settings = get_settings()
    pipelines = PaperPipelines()
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
                    label, str(paper_id)[:8], exc,
                )
    if (
        skim_result
        and skim_result.relevance_score
        >= settings.skim_score_threshold
    ):
        try:
            pipelines.deep_dive(paper_id)
        except Exception as exc:
            logger.warning(
                "deep_dive %s failed: %s",
                str(paper_id)[:8], exc,
            )


def run_topic_ingest(topic_id: str) -> dict:
    """单独处理一个主题的抓取+处理"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    pipelines = PaperPipelines()
    with session_scope() as session:
        topic = session.get(TopicSubscription, topic_id)
        if not topic:
            return {"topic_id": topic_id, "status": "not_found"}
        topic_name = topic.name

        last_error: str | None = None
        ids: list[str] = []
        attempts = 0
        for _attempt in range(topic.retry_limit + 1):
            attempts += 1
            try:
                ids = pipelines.ingest_arxiv_with_ids(
                    query=topic.query,
                    max_results=topic.max_results_per_run,
                    topic_id=topic.id,
                    action_type=ActionType.auto_collect,
                )
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

        repo = PaperRepository(session)
        all_papers = (
            repo.list_by_ids(ids)
            + repo.list_by_read_status(ReadStatus.unread, limit=50)
        )
        seen: set[str] = set()
        unique = []
        for p in all_papers:
            pid = str(p.id)
            if pid not in seen:
                seen.add(pid)
                unique.append(p)

    processed = 0
    with ThreadPoolExecutor(max_workers=PAPER_CONCURRENCY) as pool:
        futs = {pool.submit(_process_paper, p.id): p for p in unique}
        for fut in as_completed(futs):
            processed += 1
            try:
                fut.result()
            except Exception as exc:
                p = futs[fut]
                logger.warning(
                    "topic ingest process %s failed: %s",
                    str(p.id)[:8], exc,
                )

    return {
        "topic_id": topic_id,
        "topic_name": topic_name,
        "status": "ok",
        "attempts": attempts,
        "inserted": len(ids),
        "processed": processed,
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
    return DailyBriefService().publish(
        recipient=settings.notify_default_to
    )


def run_weekly_graph_maintenance() -> dict:
    with session_scope() as session:
        topics = TopicRepository(session).list_topics(
            enabled_only=True
        )
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
    incremental = graph.sync_incremental(
        paper_limit=50, edge_limit_per_paper=6
    )
    return {
        "topic_sync": topic_results,
        "incremental": incremental,
    }
