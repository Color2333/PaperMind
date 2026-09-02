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


def _topic_dict(t, session: Session | None = None) -> dict[str, Any]:
    d = {
        "id": t.id,
        "name": t.name,
        "query": t.query,
        "enabled": t.enabled,
        "max_results_per_run": t.max_results_per_run,
        "retry_limit": t.retry_limit,
        "schedule_frequency": getattr(t, "schedule_frequency", "daily"),
        "schedule_time_utc": getattr(t, "schedule_time_utc", 21),
        "enable_date_filter": getattr(t, "enable_date_filter", False),
        "date_filter_days": getattr(t, "date_filter_days", 7),
        "paper_count": 0,
        # last_run_at/last_error 读 TopicSubscription 真实抓取状态（PR1 存的），
        # 此前被 CollectionAction.created_at 覆盖掩盖了抓取失败
        "last_run_at": t.last_run_at.isoformat() if t.last_run_at else None,
        "last_error": t.last_error,
        "last_run_count": None,
        "last_action_at": None,  # 最近一次收集行动（与 last_run_at 区分）
    }
    if session is not None:
        from sqlalchemy import func, select

        from packages.storage.models import CollectionAction, PaperTopic

        cnt = session.scalar(
            select(func.count()).select_from(PaperTopic).where(PaperTopic.topic_id == t.id)
        )
        d["paper_count"] = cnt or 0
        # 最近一次收集行动（单独字段，不再覆盖 last_run_at）
        last_action = session.execute(
            select(CollectionAction)
            .where(CollectionAction.topic_id == t.id)
            .order_by(CollectionAction.created_at.desc())
            .limit(1)
        ).scalar_one_or_none()
        if last_action:
            d["last_action_at"] = (
                last_action.created_at.isoformat() if last_action.created_at else None
            )
            d["last_run_count"] = last_action.paper_count
    return d


def get_topic_info(session: Session, topic_id: str) -> dict:
    """单主题详情（fetch-status 过渡端点的 DB 兜底路径）"""
    from packages.storage.models import TopicSubscription

    topic = session.get(TopicSubscription, topic_id)
    return _topic_dict(topic, session) if topic else {}


def list_topics_with_stats(
    session: Session, *, enabled_only: bool = False, failed: bool = False
) -> dict[str, Any]:
    """主题列表 + 论文计数 + 最近行动（N+1 已批量化：3 次查询）"""
    from sqlalchemy import func, select

    from packages.storage.models import CollectionAction, PaperTopic
    from packages.storage.repositories import TopicRepository

    topics = TopicRepository(session).list_topics(enabled_only=enabled_only)
    # failed=true：只返回最近抓取出错的 topic（供可观测性面板）
    if failed:
        topics = [t for t in topics if t.last_error]
    if not topics:
        return {"items": []}
    topic_ids = [t.id for t in topics]

    # 1. 批量论文计数（GROUP BY topic_id）
    count_rows = session.execute(
        select(PaperTopic.topic_id, func.count())
        .where(PaperTopic.topic_id.in_(topic_ids))
        .group_by(PaperTopic.topic_id)
    ).all()
    paper_counts = {row[0]: row[1] for row in count_rows}

    # 2. 批量最近一次行动（按 topic 分组取 created_at 最大）
    latest_actions: dict = {}
    action_rows = (
        session.execute(
            select(CollectionAction)
            .where(CollectionAction.topic_id.in_(topic_ids))
            .order_by(CollectionAction.topic_id, CollectionAction.created_at.desc())
        )
        .scalars()
        .all()
    )
    for a in action_rows:
        if a.topic_id not in latest_actions:  # 已按 topic + created_at desc 排序，首个即最新
            latest_actions[a.topic_id] = a

    items = []
    for t in topics:
        d = {
            "id": str(t.id),
            "name": t.name,
            "query": t.query,
            "enabled": t.enabled,
            "created_at": t.created_at.isoformat() if t.created_at else None,
            "paper_count": paper_counts.get(t.id, 0),
            "last_run_at": t.last_run_at.isoformat() if t.last_run_at else None,
            "last_error": t.last_error,
            "last_action_at": None,
            "last_run_count": None,
        }
        last_action = latest_actions.get(t.id)
        if last_action:
            d["last_action_at"] = (
                last_action.created_at.isoformat() if last_action.created_at else None
            )
            d["last_run_count"] = last_action.paper_count
        items.append(d)
    return {"items": items}


def get_topic_stats(session: Session) -> dict[str, Any]:
    """主题维度统计（仓储 stats 实现）"""
    from packages.storage.repositories.stats import get_topic_stats as _stats

    return _stats(session)


def get_paper_distribution(session: Session) -> dict[str, Any]:
    """论文分布统计：年份分布 + 来源分布"""
    from packages.storage.repositories.stats import get_paper_distribution_stats as _stats

    return _stats(session)
