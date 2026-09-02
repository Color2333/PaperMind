"""内容类只读查询（B5，设计②：GetDailyBrief / GetRecommendations）"""

from __future__ import annotations


def get_daily_brief_html(limit: int = 30) -> str:
    """构建每日简报 HTML（canonical：HTML 原文；协议层自行转文本/摘要）"""
    from packages.ai.brief_service import DailyBriefService

    return DailyBriefService().build_html(limit=limit)


def get_recommendations(top_k: int = 10) -> list:
    """基于已读 embedding 的个性化推荐列表"""
    from packages.ai.recommendation_service import RecommendationService

    return RecommendationService().recommend(top_k=top_k)


def suggest_keywords(description: str) -> list:
    """AI 生成 arXiv 搜索关键词建议"""
    from packages.ai.keyword_service import KeywordService

    return KeywordService().suggest(description)


def writing_process(action: str, text: str) -> dict:
    """学术写作助手处理（WritingService；action 为合法 WritingAction 值）"""
    from packages.ai.writing_service import WritingService

    return WritingService().process(action, text)
