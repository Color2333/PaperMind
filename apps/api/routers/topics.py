"""主题订阅 & 论文摄入路由
@author Color2333
"""

import logging

from fastapi import APIRouter, HTTPException, Query

from packages.domain.schemas import ReferenceImportReq, SuggestKeywordsReq, TopicCreate, TopicUpdate
from packages.storage.db import session_scope

logger = logging.getLogger(__name__)

router = APIRouter()


def _topic_dict(t, session=None) -> dict:
    d = {
        "id": t.id,
        "name": t.name,
        "query": t.query,
        "enabled": t.enabled,
        "max_results_per_run": t.max_results_per_run,
        "retry_limit": t.retry_limit,
        "schedule_frequency": getattr(t, "schedule_frequency", "daily"),
        "schedule_time_utc": getattr(t, "schedule_time_utc", 21),
        "enable_date_filter": getattr(t, "enable_date_filter", False),
        "date_filter_days": getattr(t, "date_filter_days", 7),
        "paper_count": 0,
        # last_run_at/last_error 读 TopicSubscription 真实抓取状态（PR1 存的），
        # 此前被 CollectionAction.created_at 覆盖掩盖了抓取失败
        "last_run_at": t.last_run_at.isoformat() if t.last_run_at else None,
        "last_error": t.last_error,
        "last_run_count": None,
        "last_action_at": None,  # 最近一次收集行动（与 last_run_at 区分）
    }
    if session is not None:
        from sqlalchemy import func, select

        from packages.storage.models import CollectionAction, PaperTopic

        # 论文计数
        cnt = session.scalar(
            select(func.count()).select_from(PaperTopic).where(PaperTopic.topic_id == t.id)
        )
        d["paper_count"] = cnt or 0
        # 最近一次收集行动（单独字段，不再覆盖 last_run_at）
        last_action = session.execute(
            select(CollectionAction)
            .where(CollectionAction.topic_id == t.id)
            .order_by(CollectionAction.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if last_action:
            d["last_action_at"] = (
                last_action.created_at.isoformat() if last_action.created_at else None
            )
            d["last_run_count"] = last_action.paper_count
    return d


@router.get("/topics")
def list_topics(enabled_only: bool = False, failed: bool = False) -> dict:
    from packages.application.queries.topics import list_topics_with_stats

    with session_scope() as session:
        return list_topics_with_stats(session, enabled_only=enabled_only, failed=failed)


@router.post("/topics")
def upsert_topic(req: TopicCreate) -> dict:
    from packages.application.commands.topics import upsert_topic as app_upsert_topic

    with session_scope() as session:
        return app_upsert_topic(
            session,
            name=req.name,
            query=req.query,
            enabled=req.enabled,
            max_results_per_run=req.max_results_per_run,
            retry_limit=req.retry_limit,
            schedule_frequency=req.schedule_frequency,
            schedule_time_utc=req.schedule_time_utc,
            enable_date_filter=req.enable_date_filter,
            date_filter_days=req.date_filter_days,
        )


@router.post("/topics/suggest-keywords")
def suggest_keywords(req: SuggestKeywordsReq) -> dict:
    from packages.application.commands.content import suggest_keywords as app_suggest

    description = req.description
    if not description.strip():
        raise HTTPException(400, "description is required")
    suggestions = app_suggest(description.strip())
    return {"suggestions": suggestions}


@router.patch("/topics/{topic_id}")
def update_topic(topic_id: str, req: TopicUpdate) -> dict:
    from packages.application.commands.topics import update_topic as app_update_topic

    with session_scope() as session:
        return app_update_topic(
            session,
            topic_id,
            query=req.query,
            enabled=req.enabled,
            max_results_per_run=req.max_results_per_run,
            retry_limit=req.retry_limit,
            schedule_frequency=req.schedule_frequency,
            schedule_time_utc=req.schedule_time_utc,
            enable_date_filter=req.enable_date_filter,
            date_filter_days=req.date_filter_days,
        )


@router.delete("/topics/{topic_id}")
def delete_topic(topic_id: str) -> dict:
    from packages.application.commands.topics import delete_topic as app_delete_topic

    with session_scope() as session:
        return app_delete_topic(session, topic_id)


@router.post("/topics/{topic_id}/fetch")
def manual_fetch_topic(topic_id: str) -> dict:
    """手动触发单个订阅的论文抓取（后台执行，立即返回）"""
    from packages.application.commands.topics import start_topic_fetch

    return start_topic_fetch(topic_id)


@router.get("/topics/{topic_id}/fetch-status")
def fetch_topic_status(topic_id: str) -> dict:
    """查询手动抓取的执行状态 — 通过全局 tracker 查询（过渡；C10 并入 GetJob）"""
    from packages.application.queries.tasks import find_fetch_task_by_topic
    from packages.application.queries.topics import get_topic_info

    # 兼容旧的轮询逻辑：从 tracker 中找匹配的 fetch 任务
    matched = find_fetch_task_by_topic(topic_id)
    if matched:
        if matched["finished"]:
            return {"status": "completed" if matched["success"] else "failed", **matched}
        return {"status": "running", **matched}
    # 没找到活跃任务，看 DB 里的主题信息
    with session_scope() as session:
        topic_info = get_topic_info(session, topic_id)
    # 没找到任务时返回空字典
    return {"topic": topic_info}


# ---------- 摄入 ----------


@router.post("/ingest/arxiv")
def ingest_arxiv(
    query: str,
    max_results: int = Query(default=20, ge=1, le=200),
    topic_id: str | None = None,
    sort_by: str = Query(
        default="submittedDate", pattern="^(submittedDate|relevance|lastUpdatedDate)$"
    ),
    days_back: int = Query(
        default=0,
        ge=0,
        le=3650,
        description="只检索最近 N 天提交的论文，默认 0 = 不限日期（历史关键词搜索）；订阅可传 7/30",
    ),
) -> dict:
    from packages.application.commands.jobs import submit_job

    logger.info(
        "ArXiv ingest(task): query=%r max_results=%d sort=%s days_back=%d",
        query,
        max_results,
        sort_by,
        days_back,
    )
    # 去重第三刀：同步直调 → 提交 ingest_arxiv_query 任务（manifest A 档，
    # Go 权威调度 + 单事务 apply）；前端经 /tasks/{id}/result 轮询结果
    submitted = submit_job(
        kind="ArxivIngest",
        capability="ingest_arxiv_query",
        title=f"ArXiv 摄入: {query[:60]}",
        input_ref={
            "query": query,
            "max_results": max_results,
            "topic_id": topic_id,
            "sort_by": sort_by,
            "days_back": days_back,
        },
        idempotency_key=None,
        timeout_s=900,
        created_by="api",
    )
    return {"task_id": submitted["task_id"], "job_id": submitted["job_id"]}


@router.post("/ingest/references")
def ingest_references(body: ReferenceImportReq) -> dict:
    """一键导入参考文献 — 返回 task_id 用于轮询进度"""
    from packages.application.commands.topics import start_reference_import

    return start_reference_import(
        source_paper_id=body.source_paper_id,
        source_paper_title=body.source_paper_title,
        entries=[dict(e) for e in body.entries],
        topic_ids=body.topic_ids,
    )


@router.get("/ingest/references/status/{task_id}")
def ingest_references_status(task_id: str) -> dict:
    """查询参考文献导入任务进度"""
    from packages.application.queries.tasks import get_task_info

    task = get_task_info(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return task


# ---------- 统计 ----------


@router.get("/topics/stats")
def topic_stats() -> dict:
    """主题维度统计（30s 缓存）"""
    from apps.api.deps import cache
    from packages.application.queries.topics import get_topic_stats

    cached = cache.get("topic_stats")
    if cached is not None:
        return cached
    with session_scope() as session:
        result = get_topic_stats(session)
    cache.set("topic_stats", result, ttl=30)
    return result


@router.get("/topics/distribution")
def paper_distribution() -> dict:
    """论文分布统计：年份分布 + 来源分布（30s 缓存）"""
    from apps.api.deps import cache
    from packages.application.queries.topics import get_paper_distribution

    cached = cache.get("paper_distribution")
    if cached is not None:
        return cached
    with session_scope() as session:
        result = get_paper_distribution(session)
    cache.set("paper_distribution", result, ttl=30)
    return result
