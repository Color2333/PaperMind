"""主题订阅查询与命令（B6，设计② ListTopics / ManageTopics）"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from packages.domain.exceptions import NotFoundError

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

_FREQ_LABELS = {
    "daily": "每天",
    "twice_daily": "每天两次",
    "weekdays": "工作日",
    "weekly": "每周",
}


def list_topics(session: Session, *, enabled_only: bool = False) -> list[dict[str, Any]]:
    from packages.storage.repositories import TopicRepository

    topics = TopicRepository(session).list_topics(enabled_only=enabled_only)
    return [
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


def update_subscription(
    session: Session,
    *,
    topic_name: str,
    enabled: bool,
    schedule_frequency: str | None = None,
    schedule_time_beijing: int | None = None,
) -> dict[str, Any]:
    """启用/禁用订阅并调整调度；主题不存在抛 NotFoundError"""
    from packages.storage.repositories import TopicRepository

    topic = TopicRepository(session).get_by_name(topic_name.strip())
    if not topic:
        raise NotFoundError(f"主题「{topic_name}」不存在")
    topic.enabled = enabled
    if schedule_frequency and schedule_frequency in _FREQ_LABELS:
        topic.schedule_frequency = schedule_frequency
    if schedule_time_beijing is not None:
        utc_hour = (schedule_time_beijing - 8) % 24
        topic.schedule_time_utc = max(0, min(23, utc_hour))
    return {
        "topic": topic_name,
        "enabled": enabled,
        "schedule_frequency": schedule_frequency or "daily",
        "schedule_time_beijing": (
            schedule_time_beijing if schedule_time_beijing is not None else 5
        ),
        "schedule_frequency_effective": topic.schedule_frequency,
        "bj_hour_effective": (topic.schedule_time_utc + 8) % 24,
    }
