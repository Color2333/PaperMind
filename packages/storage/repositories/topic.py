"""
主题订阅数据仓储
@author Color2333
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from packages.storage.models import TopicSubscription


class TopicRepository:
    def __init__(self, session: Session):
        self.session = session

    def list_topics(self, enabled_only: bool = False) -> list[TopicSubscription]:
        q = select(TopicSubscription).order_by(TopicSubscription.created_at.desc())
        if enabled_only:
            q = q.where(TopicSubscription.enabled.is_(True))
        return list(self.session.execute(q).scalars())

    def get_by_name(self, name: str) -> TopicSubscription | None:
        q = select(TopicSubscription).where(TopicSubscription.name == name)
        return self.session.execute(q).scalar_one_or_none()

    def get_by_id(self, topic_id: str) -> TopicSubscription | None:
        return self.session.get(TopicSubscription, topic_id)

    def upsert_topic(
        self,
        *,
        name: str,
        query: str,
        enabled: bool = True,
        max_results_per_run: int = 20,
        retry_limit: int = 2,
        schedule_frequency: str = "daily",
        schedule_time_utc: int = 21,
        enable_date_filter: bool = False,
        date_filter_days: int = 7,
    ) -> TopicSubscription:
        found = self.get_by_name(name)
        if found:
            found.query = query
            found.enabled = enabled
            found.max_results_per_run = max(max_results_per_run, 1)
            found.retry_limit = max(retry_limit, 0)
            found.schedule_frequency = schedule_frequency
            found.schedule_time_utc = max(0, min(23, schedule_time_utc))
            found.enable_date_filter = enable_date_filter
            found.date_filter_days = max(1, date_filter_days)
            found.updated_at = datetime.now(UTC)
            self.session.flush()
            return found
        topic = TopicSubscription(
            name=name,
            query=query,
            enabled=enabled,
            max_results_per_run=max(max_results_per_run, 1),
            retry_limit=max(retry_limit, 0),
            schedule_frequency=schedule_frequency,
            schedule_time_utc=max(0, min(23, schedule_time_utc)),
            enable_date_filter=enable_date_filter,
            date_filter_days=max(1, date_filter_days),
        )
        self.session.add(topic)
        self.session.flush()
        return topic

    def update_topic(
        self,
        topic_id: str,
        *,
        query: str | None = None,
        enabled: bool | None = None,
        max_results_per_run: int | None = None,
        retry_limit: int | None = None,
        schedule_frequency: str | None = None,
        enable_date_filter: bool | None = None,
        date_filter_days: int | None = None,
        schedule_time_utc: int | None = None,
    ) -> TopicSubscription:
        topic = self.session.get(TopicSubscription, topic_id)
        if topic is None:
            raise ValueError(f"topic {topic_id} not found")
        if query is not None:
            topic.query = query
        if enabled is not None:
            topic.enabled = enabled
        if max_results_per_run is not None:
            topic.max_results_per_run = max(max_results_per_run, 1)
        if retry_limit is not None:
            topic.retry_limit = max(retry_limit, 0)
        if schedule_frequency is not None:
            topic.schedule_frequency = schedule_frequency
        if schedule_time_utc is not None:
            topic.schedule_time_utc = max(0, min(23, schedule_time_utc))
        if enable_date_filter is not None:
            topic.enable_date_filter = enable_date_filter
        if date_filter_days is not None:
            topic.date_filter_days = max(1, date_filter_days)
        topic.updated_at = datetime.now(UTC)
        self.session.flush()
        return topic

    def update_run_status(self, topic_id: str, *, error: str | None = None) -> None:
        """记录主题最近一次抓取的时间与错误（Critical #4：失败有持久化痕迹，可查可补抓）"""
        topic = self.session.get(TopicSubscription, topic_id)
        if topic is None:
            return
        topic.last_run_at = datetime.now(UTC)
        topic.last_error = None if error is None else error[:500]
        self.session.commit()

    def delete_topic(self, topic_id: str) -> None:
        topic = self.session.get(TopicSubscription, topic_id)
        if topic is not None:
            self.session.delete(topic)
