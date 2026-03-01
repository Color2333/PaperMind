"""主题订阅 & 论文摄入路由
@author Color2333
"""

import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from apps.api.deps import pipelines
from packages.domain.exceptions import NotFoundError
from packages.domain.schemas import ReferenceImportReq, SuggestKeywordsReq, TopicCreate, TopicUpdate
from packages.domain.task_tracker import global_tracker
from packages.storage.db import session_scope
from packages.storage.repositories import PaperRepository, TopicRepository

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
        "paper_count": 0,
        "last_run_at": None,
        "last_run_count": None,
    }
    if session is not None:
        from sqlalchemy import func, select
        from packages.storage.models import PaperTopic, CollectionAction

        # 论文计数
        cnt = session.scalar(
            select(func.count()).select_from(PaperTopic).where(PaperTopic.topic_id == t.id)
        )
        d["paper_count"] = cnt or 0
        # 最近一次行动
        last_action = session.execute(
            select(CollectionAction)
            .where(CollectionAction.topic_id == t.id)
            .order_by(CollectionAction.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if last_action:
            d["last_run_at"] = (
                last_action.created_at.isoformat() if last_action.created_at else None
            )
            d["last_run_count"] = last_action.paper_count
    return d


@router.get("/topics")
def list_topics(enabled_only: bool = False) -> dict:
    with session_scope() as session:
        topics = TopicRepository(session).list_topics(enabled_only=enabled_only)
        return {"items": [_topic_dict(t, session) for t in topics]}


@router.post("/topics")
def upsert_topic(req: TopicCreate) -> dict:
    with session_scope() as session:
        topic = TopicRepository(session).upsert_topic(
            name=req.name,
            query=req.query,
            enabled=req.enabled,
            max_results_per_run=req.max_results_per_run,
            retry_limit=req.retry_limit,
            schedule_frequency=req.schedule_frequency,
            schedule_time_utc=req.schedule_time_utc,
        )
        return _topic_dict(topic, session)


@router.post("/topics/suggest-keywords")
def suggest_keywords(req: SuggestKeywordsReq) -> dict:
    from packages.ai.keyword_service import KeywordService

    description = req.description
    if not description.strip():
        raise HTTPException(400, "description is required")
    suggestions = KeywordService().suggest(description.strip())
    return {"suggestions": suggestions}


@router.patch("/topics/{topic_id}")
def update_topic(topic_id: str, req: TopicUpdate) -> dict:
    with session_scope() as session:
        try:
            topic = TopicRepository(session).update_topic(
                topic_id,
                query=req.query,
                enabled=req.enabled,
                max_results_per_run=req.max_results_per_run,
                retry_limit=req.retry_limit,
                schedule_frequency=req.schedule_frequency,
                schedule_time_utc=req.schedule_time_utc,
            )
        except ValueError as exc:
            raise NotFoundError(str(exc)) from exc
        return _topic_dict(topic, session)


@router.delete("/topics/{topic_id}")
def delete_topic(topic_id: str) -> dict:
    with session_scope() as session:
        TopicRepository(session).delete_topic(topic_id)
        return {"deleted": topic_id}


@router.post("/topics/{topic_id}/fetch")
def manual_fetch_topic(topic_id: str) -> dict:
    """手动触发单个订阅的论文抓取（后台执行，立即返回）"""
    from packages.ai.daily_runner import run_topic_ingest
    from packages.storage.models import TopicSubscription

    with session_scope() as session:
        topic = session.get(TopicSubscription, topic_id)
        if not topic:
            raise NotFoundError("订阅不存在")
        topic_name = topic.name

    def _fetch_fn(progress_callback=None):
        return run_topic_ingest(topic_id)

    task_id = global_tracker.submit(
        task_type="fetch",
        title=f"抓取: {topic_name[:30]}",
        fn=_fetch_fn,
    )
    return {
        "status": "started",
        "task_id": task_id,
        "topic_id": topic_id,
        "topic_name": topic_name,
        "message": f"「{topic_name}」抓取已在后台启动",
    }


@router.get("/topics/{topic_id}/fetch-status")
def fetch_topic_status(topic_id: str) -> dict:
    """查询手动抓取的执行状态 — 通过全局 tracker 查询"""
    # 兼容旧的轮询逻辑：从 tracker 中找匹配的 fetch 任务
    active = global_tracker.get_active()
    for t in active:
        if t["task_type"] == "fetch" and topic_id[:8] in t.get("task_id", ""):
            if t["finished"]:
                return {"status": "completed" if t["success"] else "failed", **t}
            return {"status": "running", **t}
    # 没找到活跃任务，看 DB 里的主题信息
    with session_scope() as session:
        from packages.storage.models import TopicSubscription

        topic = session.get(TopicSubscription, topic_id)
        topic_info = _topic_dict(topic, session) if topic else {}
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
) -> dict:
    logger.info("ArXiv ingest: query=%r max_results=%d sort=%s", query, max_results, sort_by)
    count, inserted_ids, _ = pipelines.ingest_arxiv(
        query=query,
        max_results=max_results,
        topic_id=topic_id,
        sort_by=sort_by,
    )
    # 查询插入论文的基本信息
    papers_info: list[dict] = []
    if inserted_ids:
        with session_scope() as session:
            repo = PaperRepository(session)
            for pid in inserted_ids[:50]:
                try:
                    p = repo.get_by_id(UUID(pid))
                    papers_info.append(
                        {
                            "id": p.id,
                            "title": p.title,
                            "arxiv_id": p.arxiv_id,
                            "publication_date": p.publication_date.isoformat()
                            if p.publication_date
                            else None,
                        }
                    )
                except Exception:
                    pass
    return {"ingested": count, "papers": papers_info}


@router.post("/ingest/references")
def ingest_references(body: ReferenceImportReq) -> dict:
    """一键导入参考文献 — 返回 task_id 用于轮询进度"""
    from packages.ai.pipelines import ReferenceImporter

    importer = ReferenceImporter()
    task_id = importer.start_import(
        source_paper_id=body.source_paper_id,
        source_paper_title=body.source_paper_title,
        entries=[dict(e) for e in body.entries],
        topic_ids=body.topic_ids,
    )
    return {"task_id": task_id, "total": len(body.entries)}


@router.get("/ingest/references/status/{task_id}")
def ingest_references_status(task_id: str) -> dict:
    """查询参考文献导入任务进度"""
    from packages.ai.pipelines import get_import_task

    task = get_import_task(task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return task
