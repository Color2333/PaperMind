"""内容类只读查询（B5/B7，设计②：GetDailyBrief / GetRecommendations / GetTrends / 生成产物）"""

from __future__ import annotations

from datetime import UTC
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def _iso_dt(dt) -> str | None:
    """确保返回带时区的 ISO 格式（SQLite 读出来的可能是 naive datetime）"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.isoformat()


def get_recommendations(top_k: int = 10) -> list:
    """基于已读 embedding 的个性化推荐列表"""
    from packages.ai.recommendation_service import RecommendationService

    return RecommendationService().recommend(top_k=top_k)


def list_generated_contents(session: Session, *, content_type: str, limit: int = 50) -> dict:
    from packages.storage.repositories import GeneratedContentRepository

    items = GeneratedContentRepository(session).list_by_type(content_type, limit=limit)
    return {
        "items": [
            {
                "id": gc.id,
                "content_type": gc.content_type,
                "title": gc.title,
                "keyword": gc.keyword,
                "paper_id": gc.paper_id,
                "created_at": _iso_dt(gc.created_at),
            }
            for gc in items
        ]
    }


def get_generated_content(session: Session, content_id: str) -> dict:
    """生成产物详情；不存在抛 NotFoundError"""
    from packages.domain.exceptions import NotFoundError
    from packages.storage.repositories import GeneratedContentRepository

    try:
        gc = GeneratedContentRepository(session).get_by_id(content_id)
    except ValueError as exc:
        raise NotFoundError("Content not found") from exc
    return {
        "id": gc.id,
        "content_type": gc.content_type,
        "title": gc.title,
        "keyword": gc.keyword,
        "paper_id": gc.paper_id,
        "markdown": gc.markdown,
        "metadata_json": gc.metadata_json,
        "created_at": _iso_dt(gc.created_at),
    }


def get_trends_hot(*, days: int = 7, top_k: int = 15) -> dict:
    from packages.ai.recommendation_service import TrendService

    return {"items": TrendService().detect_hot_keywords(days=days, top_k=top_k)}


def get_trends_emerging(*, days: int = 14) -> dict:
    from packages.ai.recommendation_service import TrendService

    return TrendService().detect_trends(days=days)


def get_today_summary() -> dict:
    from packages.ai.recommendation_service import TrendService

    return TrendService().get_today_summary()
