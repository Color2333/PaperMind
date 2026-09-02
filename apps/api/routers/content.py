"""Wiki / 简报 / 生成内容 / 趋势路由
@author Color2333
"""

from fastapi import APIRouter, HTTPException, Query

from apps.api.deps import brief_service, cache
from packages.application.commands.generated import save_generated_content
from packages.application.queries import content as content_queries
from packages.application.queries import graph as graph_queries
from packages.domain.exceptions import NotFoundError
from packages.domain.schemas import DailyBriefRequest
from packages.domain.task_tracker import global_tracker
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


def _run_topic_wiki_task(
    keyword: str,
    limit: int,
    progress_callback=None,
) -> dict:
    """后台执行 topic wiki 生成"""

    # task_tracker 传入的 progress_callback 签名为 (msg, cur, tot)
    # graph topic_wiki 内部已按 (msg, cur, tot) 调用，此处透传
    def _adapted_progress(pct: float, msg: str):
        if progress_callback:
            progress_callback(msg, int(pct * 100), 100)

    from packages.application.commands.generated import save_generated_content
    from packages.application.queries.graph import get_topic_wiki

    result = get_topic_wiki(
        keyword=keyword,
        limit=limit,
        progress_callback=_adapted_progress,
    )
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
        category="generation",
    )
    return {"task_id": task_id, "status": "pending"}


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
    # 写路径（B8 统一命令面）；暂保留仓储直调，仅恢复局部导入
    from packages.storage.repositories import GeneratedContentRepository

    with session_scope() as session:
        repo = GeneratedContentRepository(session)
        try:
            repo.get_by_id(content_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Content not found") from None
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
        if progress_callback:
            progress_callback("正在生成每日简报...", 20, 100)
        result = brief_service.publish(recipient=recipient)
        if progress_callback:
            progress_callback("简报生成完成", 95, 100)
        return result

    task_id = global_tracker.submit(
        task_type="daily_brief",
        title="📰 生成每日简报",
        fn=_generate_fn,
        total=100,
        category="generation",
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
