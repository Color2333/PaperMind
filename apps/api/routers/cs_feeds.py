"""CS 分类订阅 API
@author Color2333
"""

import logging

from fastapi import APIRouter, Depends, Query, Request

from packages.domain.task_tracker import global_tracker
from packages.storage.db import SessionLocal
from packages.storage.repositories import CSFeedRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/cs", tags=["cs-feeds"])


def get_repo():
    session = SessionLocal()
    try:
        yield CSFeedRepository(session)
    finally:
        session.close()


class CategoryInfo:
    def __init__(self, code: str, name: str, description: str = ""):
        self.code = code
        self.name = name
        self.description = description


class FeedInfo:
    def __init__(
        self,
        category_code: str,
        category_name: str,
        daily_limit: int,
        enabled: bool,
        status: str,
        last_run_at: str | None,
        last_run_count: int,
    ):
        self.category_code = category_code
        self.category_name = category_name
        self.daily_limit = daily_limit
        self.enabled = enabled
        self.status = status
        self.last_run_at = last_run_at
        self.last_run_count = last_run_count


@router.get("/categories")
def list_categories(repo: CSFeedRepository = Depends(get_repo)):
    categories = repo.get_categories()
    return {
        "categories": [
            {"code": c.code, "name": c.name, "description": c.description} for c in categories
        ]
    }


@router.get("/feeds")
def list_feeds(repo: CSFeedRepository = Depends(get_repo)):
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


@router.post("/feeds")
async def subscribe(
    repo: CSFeedRepository = Depends(get_repo),
    category_codes: list[str] | None = Query(default=None, alias="category_codes"),
    daily_limit: int = Query(default=30, alias="daily_limit"),
    enabled: bool = Query(default=True, alias="enabled"),
    request: Request = None,
):
    if category_codes is None and request is not None:
        body = await request.json()
        category_codes = body.get("category_codes", [])
        daily_limit = body.get("daily_limit", 30)
        enabled = body.get("enabled", True)
    if not category_codes:
        category_codes = []
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


@router.delete("/feeds/{category_code}")
def unsubscribe(category_code: str, repo: CSFeedRepository = Depends(get_repo)):
    deleted = repo.delete_subscription(category_code)
    return {"deleted": deleted}


@router.patch("/feeds/{category_code}")
def update_feed(
    category_code: str,
    daily_limit: int | None = Query(default=None, alias="daily_limit"),
    enabled: bool | None = Query(default=None, alias="enabled"),
    repo: CSFeedRepository = Depends(get_repo),
):
    sub = repo.get_subscription(category_code)
    if not sub:
        return {"error": "订阅不存在"}
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


@router.post("/feeds/{category_code}/fetch")
def fetch_category(
    category_code: str,
    repo: CSFeedRepository = Depends(get_repo),
):
    """手动触发单个分类的论文抓取（后台任务）"""
    sub = repo.get_subscription(category_code)
    if not sub:
        return {"error": "订阅不存在"}

    def _fetch_fn(progress_callback=None):
        from packages.integrations.arxiv_client import ArxivClient
        from packages.storage.db import session_scope
        from packages.storage.repositories import PaperRepository

        if progress_callback:
            progress_callback("正在获取论文列表...", 10, 100)
        client = ArxivClient()
        papers = client.fetch_latest(
            query=f"cat:{category_code}",
            max_results=sub.daily_limit,
            days_back=7,
        )

        total_papers = len(papers)
        if progress_callback:
            progress_callback(f"开始入库 ({total_papers} 篇)...", 50, 100)

        count = 0
        with session_scope() as session:
            paper_repo = PaperRepository(session)
            for i, p in enumerate(papers):
                paper_repo.upsert_paper(p)
                count += 1
                if progress_callback:
                    progress_callback(
                        f"入库中 ({i + 1}/{total_papers})...",
                        50 + int((i + 1) / total_papers * 40),
                        100,
                    )
            repo.update_run_status(category_code, count)

        if progress_callback:
            progress_callback("抓取完成", 95, 100)
        return {"fetched": count}

    task_id = global_tracker.submit(
        task_type="cs_feed_fetch",
        title=f"📥 抓取分类: {category_code}",
        fn=_fetch_fn,
    )
    return {
        "status": "started",
        "task_id": task_id,
        "message": f"「{category_code}」抓取已在后台启动",
    }
