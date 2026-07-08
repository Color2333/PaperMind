"""主题订阅列表与管理。"""

from __future__ import annotations

import logging

from packages.ai.tools.types import ToolResult
from packages.storage.db import session_scope
from packages.storage.repositories import TopicRepository

logger = logging.getLogger(__name__)


def _list_topics() -> ToolResult:
    try:
        with session_scope() as session:
            topics = TopicRepository(session).list_topics(enabled_only=False)
            items = [
                {
                    "id": str(t.id),
                    "name": t.name,
                    "query": t.query,
                    "enabled": t.enabled,
                    "paper_count": getattr(t, "paper_count", None),
                    "max_results_per_run": t.max_results_per_run,
                    "retry_limit": t.retry_limit,
                }
                for t in topics
            ]
        enabled = sum(1 for t in items if t["enabled"])
        names = ", ".join(t["name"] for t in items[:5])
        suffix = "..." if len(items) > 5 else ""
        return ToolResult(
            success=True,
            data={"topics": items, "count": len(items)},
            summary=f"共 {len(items)} 个主题（{enabled} 个已订阅）: {names}{suffix}",
        )
    except Exception as exc:
        logger.exception("list_topics failed: %s", exc)
        return ToolResult(success=False, summary=f"列出主题失败: {exc!s}")


def _manage_subscription(
    topic_name: str,
    enabled: bool,
    schedule_frequency: str | None = None,
    schedule_time_beijing: int | None = None,
) -> ToolResult:
    """管理主题订阅：启用/禁用、设置频率和时间"""
    freq_map = {
        "daily": "每天",
        "twice_daily": "每天两次",
        "weekdays": "工作日",
        "weekly": "每周",
    }
    with session_scope() as session:
        topic_repo = TopicRepository(session)
        topic = topic_repo.get_by_name(topic_name.strip())
        if not topic:
            return ToolResult(
                success=False,
                summary=f"主题「{topic_name}」不存在",
            )
        topic.enabled = enabled
        if schedule_frequency and schedule_frequency in freq_map:
            topic.schedule_frequency = schedule_frequency
        if schedule_time_beijing is not None:
            utc_hour = (schedule_time_beijing - 8) % 24
            topic.schedule_time_utc = max(0, min(23, utc_hour))

        freq_label = freq_map.get(topic.schedule_frequency, topic.schedule_frequency)
        bj_hour = (topic.schedule_time_utc + 8) % 24
        action = "启用定时搜集" if enabled else "关闭定时搜集"
        schedule_info = f"（{freq_label} · 北京时间 {bj_hour:02d}:00）"

    return ToolResult(
        success=True,
        data={
            "topic": topic_name,
            "enabled": enabled,
            "schedule_frequency": schedule_frequency or "daily",
            "schedule_time_beijing": (
                schedule_time_beijing if schedule_time_beijing is not None else 5
            ),
        },
        summary=f"已{action}：{topic_name} {schedule_info}",
    )
