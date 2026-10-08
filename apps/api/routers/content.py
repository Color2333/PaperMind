"""Wiki / 简报 / 生成内容 / 趋势路由
@author Color2333
"""

from fastapi import APIRouter, HTTPException, Query

from apps.api.deps import cache
from packages.application.commands.generated import save_generated_content
from packages.application.queries import content as content_queries
from packages.application.queries import graph as graph_queries
from packages.domain.exceptions import NotFoundError
from packages.domain.schemas import DailyBriefRequest
from packages.storage.db import session_scope

router = APIRouter()


# ---------- Wiki ----------


@router.get("/wiki/paper/{paper_id}")
def wiki_paper(paper_id: str) -> dict:
    result = graph_queries.get_paper_wiki(paper_id=paper_id)
    with session_scope() as session:
        result["content_id"] = save_generated_content(
            session,
            content_type="paper_wiki",
            title=f"Paper Wiki: {result.get('title', paper_id)}",
            markdown=result.get("markdown", ""),
            paper_id=paper_id,
            metadata_json={k: v for k, v in result.items() if k != "markdown"},
        )
    return result


@router.get("/wiki/topic")
def wiki_topic(
    keyword: str,
    limit: int = Query(default=120, ge=1, le=500),
) -> dict:
    result = graph_queries.get_topic_wiki(keyword=keyword, limit=limit)
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


# ---------- 异步任务 API ----------


@router.post("/tasks/wiki/topic")
def start_topic_wiki_task(
    keyword: str,
    limit: int = Query(default=120, ge=1, le=500),
) -> dict:
    """提交后台 wiki 生成任务（业务在 application/commands/wiki.py）"""
    from packages.application.commands.wiki import start_topic_wiki_with_save

    return start_topic_wiki_with_save(keyword=keyword, limit=limit)


# ---------- 生成内容历史 ----------


@router.get("/generated/list")
def generated_list(
    type: str = Query(..., description="content_type: topic_wiki|paper_wiki|daily_brief"),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    with session_scope() as session:
        return content_queries.list_generated_contents(session, content_type=type, limit=limit)


@router.get("/generated/{content_id}")
def generated_detail(content_id: str) -> dict:
    with session_scope() as session:
        try:
            return content_queries.get_generated_content(session, content_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail="Content not found") from exc


@router.delete("/generated/{content_id}")
def generated_delete(content_id: str) -> dict:
    from packages.application.commands.generated import delete_generated_content
    from packages.domain.exceptions import NotFoundError

    with session_scope() as session:
        try:
            return delete_generated_content(session, content_id)
        except NotFoundError as exc:
            raise HTTPException(status_code=404, detail="Content not found") from exc


# ---------- 简报 ----------


@router.post("/brief/daily")
def daily_brief(req: DailyBriefRequest) -> dict:
    """生成每日简报（异步任务；业务在 application/commands/brief.py）"""
    from packages.application.commands.brief import start_daily_brief_task

    return start_daily_brief_task(recipient=req.recipient)


# ---------- 推荐 & 趋势 ----------


@router.get("/trends/hot")
def hot_keywords(
    days: int = Query(default=7, ge=1, le=30),
    top_k: int = Query(default=15, ge=1, le=50),
) -> dict:
    return content_queries.get_trends_hot(days=days, top_k=top_k)


@router.get("/trends/emerging")
def emerging_trends(days: int = Query(default=14, ge=7, le=60)) -> dict:
    return content_queries.get_trends_emerging(days=days)


@router.get("/today")
def today_summary() -> dict:
    """今日研究速览（60s 缓存，内容变化慢；缓存在传输层，业务在 application）"""
    cached = cache.get("today_summary")
    if cached is not None:
        return cached
    result = content_queries.get_today_summary()
    cache.set("today_summary", result, ttl=60)
    return result
