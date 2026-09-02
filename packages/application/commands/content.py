"""内容生成命令（B8 边界修正：写作与关键词建议产生 LLM 成本）"""

from __future__ import annotations


def suggest_keywords(description: str) -> list:
    """AI 生成 arXiv 搜索关键词建议"""
    from packages.ai.keyword_service import KeywordService

    return KeywordService().suggest(description)


def writing_process(action: str, text: str) -> dict:
    """学术写作助手处理（WritingService；action 为合法 WritingAction 值）"""
    from packages.ai.writing_service import WritingService

    return WritingService().process(action, text)


def get_daily_brief_html(limit: int = 30) -> str:
    """构建每日简报 HTML（canonical：HTML 原文；含 LLM 生成段，属生成命令）"""
    from packages.ai.brief_service import DailyBriefService

    return DailyBriefService().build_html(limit=limit)
