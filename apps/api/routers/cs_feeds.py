"""CS 分类订阅 API（业务在 application/commands/cs_feeds.py）
@author Color2333
"""

import logging

from fastapi import APIRouter, Query, Request
from fastapi import Depends as FastAPIDepends

from packages.application.commands import cs_feeds as cs_commands
from packages.domain.exceptions import NotFoundError
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


@router.get("/categories")
def list_categories(repo: CSFeedRepository = FastAPIDepends(get_repo)):
    with SessionLocal() as session:
        return cs_commands.list_categories(session)


@router.get("/feeds")
def list_feeds(repo: CSFeedRepository = FastAPIDepends(get_repo)):
    with SessionLocal() as session:
        return cs_commands.list_feeds(session)


@router.post("/feeds")
async def subscribe(
    repo: CSFeedRepository = FastAPIDepends(get_repo),
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
    with SessionLocal() as session:
        return cs_commands.subscribe(
            session, category_codes=category_codes, daily_limit=daily_limit, enabled=enabled
        )


@router.delete("/feeds/{category_code}")
def unsubscribe(category_code: str, repo: CSFeedRepository = FastAPIDepends(get_repo)):
    with SessionLocal() as session:
        return cs_commands.unsubscribe(session, category_code=category_code)


@router.patch("/feeds/{category_code}")
def update_feed(
    category_code: str,
    daily_limit: int | None = Query(default=None, alias="daily_limit"),
    enabled: bool | None = Query(default=None, alias="enabled"),
    repo: CSFeedRepository = FastAPIDepends(get_repo),
):
    try:
        with SessionLocal() as session:
            return cs_commands.update_feed(
                session, category_code=category_code, daily_limit=daily_limit, enabled=enabled
            )
    except NotFoundError as exc:
        return {"error": str(exc)}


@router.post("/feeds/{category_code}/fetch")
def fetch_category(
    category_code: str,
    repo: CSFeedRepository = FastAPIDepends(get_repo),
):
    """手动触发单个分类的论文抓取（后台任务）"""
    try:
        with SessionLocal() as session:
            return cs_commands.start_feed_fetch(session, category_code=category_code)
    except NotFoundError as exc:
        return {"error": str(exc)}
