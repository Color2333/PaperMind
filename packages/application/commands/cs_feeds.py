"""CS 分类订阅命令（B8 后期，设计② ManageCsFeeds / StartFeedFetch）"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from packages.domain.exceptions import NotFoundError

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from packages.storage.repositories import CSFeedRepository


def _sub_dict(sub: Any, category_name: str | None = None) -> dict[str, Any]:
    d = {
        "category_code": sub.category_code,
        "daily_limit": sub.daily_limit,
        "enabled": sub.enabled,
    }
    if hasattr(sub, "status"):
        d["status"] = sub.status
    if hasattr(sub, "last_run_at"):
        d["last_run_at"] = sub.last_run_at.isoformat() if sub.last_run_at else None
    if hasattr(sub, "last_run_count"):
        d["last_run_count"] = sub.last_run_count
    if category_name:
        d["category_name"] = category_name
    return d


def list_categories(session: Session) -> dict[str, Any]:
    from packages.storage.repositories import CSFeedRepository

    repo: CSFeedRepository = CSFeedRepository(session)
    categories = repo.get_categories()
    return {
        "categories": [
            {"code": c.code, "name": c.name, "description": c.description} for c in categories
        ]
    }


def list_feeds(session: Session) -> dict[str, Any]:
    from packages.storage.repositories import CSFeedRepository

    repo: CSFeedRepository = CSFeedRepository(session)
    feeds = repo.get_subscriptions()
    categories = {c.code: c.name for c in repo.get_categories()}
    return {
        "feeds": [
            {
                "category_code": f.category_code,
                "category_name": categories.get(f.category_code, f.category_code),
                "daily_limit": f.daily_limit,
                "enabled": f.enabled,
                "status": f.status,
                "last_run_at": f.last_run_at.isoformat() if f.last_run_at else None,
                "last_run_count": f.last_run_count,
            }
            for f in feeds
        ]
    }


def subscribe(
    session: Session, *, category_codes: list[str], daily_limit: int = 30, enabled: bool = True
) -> dict[str, Any]:
    from packages.storage.repositories import CSFeedRepository

    repo: CSFeedRepository = CSFeedRepository(session)
    created = []
    for code in category_codes:
        sub = repo.upsert_subscription(code, daily_limit, enabled)
        created.append(
            {
                "category_code": sub.category_code,
                "daily_limit": sub.daily_limit,
                "enabled": sub.enabled,
            }
        )
    return {"created": len(created), "feeds": created}


def unsubscribe(session: Session, *, category_code: str) -> dict[str, Any]:
    from packages.storage.repositories import CSFeedRepository

    deleted = CSFeedRepository(session).delete_subscription(category_code)
    return {"deleted": deleted}


def update_feed(
    session: Session,
    *,
    category_code: str,
    daily_limit: int | None = None,
    enabled: bool | None = None,
) -> dict[str, Any]:
    from packages.storage.repositories import CSFeedRepository

    repo: CSFeedRepository = CSFeedRepository(session)
    sub = repo.get_subscription(category_code)
    if not sub:
        raise NotFoundError("订阅不存在")
    if daily_limit is not None:
        sub.daily_limit = daily_limit
    if enabled is not None:
        sub.enabled = enabled
    repo.session.commit()
    return {
        "category_code": sub.category_code,
        "daily_limit": sub.daily_limit,
        "enabled": sub.enabled,
    }


def _fetch_category_impl(*, category_code: str, progress=None) -> dict[str, Any]:
    """单个 CS 分类的抓取+入库执行体（task_handlers.cs_feed_fetch_category 调用）"""
    from packages.ai.cs_feed_orchestrator import CSFeedOrchestrator
    from packages.integrations.arxiv_client import ArxivClient
    from packages.storage.db import session_scope
    from packages.storage.repositories import CSFeedRepository, PaperRepository

    with session_scope() as session:
        repo: CSFeedRepository = CSFeedRepository(session)
        sub = repo.get_subscription(category_code)
        if not sub:
            raise NotFoundError("订阅不存在")
        daily_limit = sub.daily_limit

    if progress:
        progress("正在获取论文列表...", 10, 100)
    papers = ArxivClient().fetch_latest(
        query=f"cat:{category_code}", max_results=daily_limit, days_back=7
    )

    total_papers = len(papers)
    if progress:
        progress(f"开始入库 ({total_papers} 篇)...", 50, 100)

    count = 0
    paper_ids: list[str] = []
    with session_scope() as session2:
        paper_repo = PaperRepository(session2)
        cs_repo = CSFeedRepository(session2)
        for i, p in enumerate(papers):
            saved = paper_repo.upsert_paper(p)
            count += 1
            paper_ids.append(saved.id)
            if progress:
                progress(
                    f"入库中 ({i + 1}/{total_papers})...",
                    50 + int((i + 1) / total_papers * 40),
                    100,
                )
        if paper_ids:
            CSFeedOrchestrator._link_cs_papers_to_topic(session2, category_code, paper_ids)
        cs_repo.update_run_status(category_code, count)

    if paper_ids:
        CSFeedOrchestrator._trigger_auto_link(paper_ids)

    if progress:
        progress("抓取完成", 95, 100)
    return {"fetched": count}


def start_feed_fetch(session: Session, *, category_code: str) -> dict[str, Any]:
    """手动触发单个分类的论文抓取（durable Job，Executor 执行）"""
    from packages.application.commands.jobs import submit_job
    from packages.application.commands.task_registry import get_spec

    submitted = submit_job(
        kind="CSFeedFetch",
        capability="cs_feed_fetch_category",
        title=f"📥 抓取分类: {category_code}",
        input_ref={"category_code": category_code},
        resource_class=get_spec("cs_feed_fetch_category").resource_class,
        timeout_s=get_spec("cs_feed_fetch_category").timeout_s,
        max_attempts=get_spec("cs_feed_fetch_category").max_attempts,
        created_by="api",
    )
    return {
        "status": "started",
        "task_id": submitted["task_id"],
        "job_id": submitted["job_id"],
        "message": f"「{category_code}」抓取已在后台启动",
    }
