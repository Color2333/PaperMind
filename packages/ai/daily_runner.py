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
from packages.domain.enums import ReadStatus
from packages.storage.db import session_scope
from packages.storage.repositories import (
    PaperRepository,
    TopicRepository,
)

logger = logging.getLogger(__name__)


def run_daily_ingest() -> dict:
    settings = get_settings()
    pipelines = PaperPipelines()
    with session_scope() as session:
        repo = PaperRepository(session)
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
        newly_inserted_ids: list[str] = []
        topic_runs: list[dict] = []
        for topic in topics:
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
                    )
                    last_error = None
                    break
                except Exception as exc:
                    last_error = str(exc)
            if last_error is not None:
                topic_runs.append(
                    {
                        "topic_id": topic.id,
                        "topic_name": topic.name,
                        "status": "failed",
                        "attempts": attempts,
                        "error": last_error,
                        "inserted": 0,
                    }
                )
                continue
            newly_inserted_ids.extend(ids)
            topic_runs.append(
                {
                    "topic_id": topic.id,
                    "topic_name": topic.name,
                    "status": "ok",
                    "attempts": attempts,
                    "inserted": len(ids),
                }
            )

        processed = 0
        latest = repo.list_by_ids(newly_inserted_ids)
        for paper in latest:
            skim = pipelines.skim(paper.id)
            if skim.relevance_score >= settings.skim_score_threshold:
                pipelines.deep_dive(paper.id)
            pipelines.embed_paper(paper.id)
            processed += 1

        backlog = repo.list_by_read_status(
            ReadStatus.unread, limit=50
        )
        for paper in backlog:
            skim = pipelines.skim(paper.id)
            if skim.relevance_score >= settings.skim_score_threshold:
                pipelines.deep_dive(paper.id)
            pipelines.embed_paper(paper.id)
            processed += 1

    return {
        "newly_inserted": len(newly_inserted_ids),
        "processed": processed,
        "topics": topic_runs,
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
