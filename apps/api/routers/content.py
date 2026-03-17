"""Wiki / 简报 / 生成内容 / 趋势路由
@author Color2333
"""

from fastapi import APIRouter, HTTPException, Query

from apps.api.deps import brief_date, brief_service, cache, graph_service, iso_dt, settings
from packages.domain.schemas import DailyBriefRequest
from packages.domain.task_tracker import global_tracker
from packages.storage.db import session_scope
from packages.storage.repositories import GeneratedContentRepository

router = APIRouter()


# ---------- Wiki ----------


@router.get("/wiki/paper/{paper_id}")
def wiki_paper(paper_id: str) -> dict:
    result = graph_service.paper_wiki(paper_id=paper_id)
    with session_scope() as session:
        repo = GeneratedContentRepository(session)
        gc = repo.create(
            content_type="paper_wiki",
            title=f"Paper Wiki: {result.get('title', paper_id)}",
            markdown=result.get("markdown", ""),
            paper_id=paper_id,
            metadata_json={k: v for k, v in result.items() if k != "markdown"},
        )
        result["content_id"] = gc.id
    return result


@router.get("/wiki/topic")
def wiki_topic(
    keyword: str,
    limit: int = Query(default=120, ge=1, le=500),
) -> dict:
    result = graph_service.topic_wiki(keyword=keyword, limit=limit)
    with session_scope() as session:
        repo = GeneratedContentRepository(session)
        gc = repo.create(
            content_type="topic_wiki",
            title=f"Topic Wiki: {keyword}",
            markdown=result.get("markdown", ""),
            keyword=keyword,
            metadata_json={k: v for k, v in result.items() if k != "markdown"},
        )
        result["content_id"] = gc.id
    return result


# ---------- 异步任务 API ----------


def _run_topic_wiki_task(
    keyword: str,
    limit: int,
    progress_callback=None,
) -> dict:
    """后台执行 topic wiki 生成"""

    # task_tracker 传入的 progress_callback 签名为 (msg, cur, tot)
    # graph_service.topic_wiki 期望的签名为 (pct: float, msg: str)
    # 做适配器转换
    def _adapted_progress(pct: float, msg: str):
        if progress_callback:
            progress_callback(msg, int(pct * 100), 100)

    result = graph_service.topic_wiki(
        keyword=keyword,
        limit=limit,
        progress_callback=_adapted_progress,
    )
    with session_scope() as session:
        repo = GeneratedContentRepository(session)
        gc = repo.create(
            content_type="topic_wiki",
            title=f"Topic Wiki: {keyword}",
            markdown=result.get("markdown", ""),
            keyword=keyword,
            metadata_json={k: v for k, v in result.items() if k != "markdown"},
        )
        result["content_id"] = gc.id
    return result


@router.post("/tasks/wiki/topic")
def start_topic_wiki_task(
    keyword: str,
    limit: int = Query(default=120, ge=1, le=500),
) -> dict:
    """提交后台 wiki 生成任务"""
    task_id = global_tracker.submit(
        task_type="topic_wiki",
        title=f"Wiki: {keyword}",
        fn=_run_topic_wiki_task,
        keyword=keyword,
        limit=limit,
    )
    return {"task_id": task_id, "status": "pending"}


# ---------- 生成内容历史 ----------


@router.get("/generated/list")
def generated_list(
    type: str = Query(..., description="content_type: topic_wiki|paper_wiki|daily_brief"),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    with session_scope() as session:
        repo = GeneratedContentRepository(session)
        items = repo.list_by_type(type, limit=limit)
        return {
            "items": [
                {
                    "id": gc.id,
                    "content_type": gc.content_type,
                    "title": gc.title,
                    "keyword": gc.keyword,
                    "paper_id": gc.paper_id,
                    "created_at": iso_dt(gc.created_at),
                }
                for gc in items
            ]
        }


@router.get("/generated/{content_id}")
def generated_detail(content_id: str) -> dict:
    with session_scope() as session:
        repo = GeneratedContentRepository(session)
        try:
            gc = repo.get_by_id(content_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Content not found")
        return {
            "id": gc.id,
            "content_type": gc.content_type,
            "title": gc.title,
            "keyword": gc.keyword,
            "paper_id": gc.paper_id,
            "markdown": gc.markdown,
            "metadata_json": gc.metadata_json,
            "created_at": iso_dt(gc.created_at),
        }


@router.delete("/generated/{content_id}")
def generated_delete(content_id: str) -> dict:
    with session_scope() as session:
        repo = GeneratedContentRepository(session)
        try:
            repo.get_by_id(content_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Content not found")
        repo.delete(content_id)
    return {"deleted": content_id}


# ---------- 简报 ----------


@router.post("/brief/daily")
def daily_brief(req: DailyBriefRequest) -> dict:
    """生成每日简报（异步任务）"""
    from packages.domain.task_tracker import global_tracker

    # 如果没有指定收件人，从数据库读取配置
    recipient = req.recipient
    if not recipient:
        from packages.storage.db import session_scope
        from packages.storage.repositories import DailyReportConfigRepository

        with session_scope() as session:
            config = DailyReportConfigRepository(session).get_config()
            if config.send_email_report and config.recipient_emails:
                recipient = config.recipient_emails.split(",")[0]

    def _generate_fn(progress_callback=None):
        # publish() 内部已写入 generated_content 表，无需重复
        return brief_service.publish(recipient=recipient)

    task_id = global_tracker.submit(
        task_type="daily_brief",
        title="📰 生成每日简报",
        fn=_generate_fn,
        total=100,
    )
    return {
        "task_id": task_id,
        "status": "started",
        "message": "日报生成已启动，预计需要 1-3 分钟...",
    }


# ---------- 推荐 & 趋势 ----------


@router.get("/trends/hot")
def hot_keywords(
    days: int = Query(default=7, ge=1, le=30),
    top_k: int = Query(default=15, ge=1, le=50),
) -> dict:
    from packages.ai.recommendation_service import TrendService

    items = TrendService().detect_hot_keywords(days=days, top_k=top_k)
    return {"items": items}


@router.get("/trends/emerging")
def emerging_trends(days: int = Query(default=14, ge=7, le=60)) -> dict:
    from packages.ai.recommendation_service import TrendService

    return TrendService().detect_trends(days=days)


@router.get("/today")
def today_summary() -> dict:
    """今日研究速览（60s 缓存，内容变化慢）"""
    cached = cache.get("today_summary")
    if cached is not None:
        return cached
    from packages.ai.recommendation_service import TrendService

    result = TrendService().get_today_summary()
    cache.set("today_summary", result, ttl=60)
    return result
