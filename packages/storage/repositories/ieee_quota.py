"""
IEEE API 配额管理数据仓储
@author Color2333
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from packages.storage.models import IeeeApiQuota


class IeeeQuotaRepository:
    """IEEE API 配额管理 Repository"""

    def __init__(self, session: Session):
        from packages.storage.models import IeeeApiQuota

        self.session = session
        self.IeeeApiQuota = IeeeApiQuota

    def get_or_create(self, topic_id: str, date: date, limit: int = 50) -> IeeeApiQuota:
        """获取或创建当日配额记录"""
        from sqlalchemy import select

        q = select(self.IeeeApiQuota).where(
            self.IeeeApiQuota.topic_id == topic_id,
            self.IeeeApiQuota.date == date,
        )
        quota = self.session.execute(q).scalar_one_or_none()

        if not quota:
            quota = self.IeeeApiQuota(
                topic_id=topic_id,
                date=date,
                api_calls_used=0,
                api_calls_limit=limit,
            )
            self.session.add(quota)
            self.session.flush()

        return quota

    def check_quota(self, topic_id: str, date: date, limit: int = 50) -> bool:
        """检查是否还有配额"""
        quota = self.get_or_create(topic_id, date, limit)
        return quota.api_calls_used < quota.api_calls_limit

    def consume_quota(self, topic_id: str, date: date, amount: int = 1) -> bool:
        """消耗配额"""
        quota = self.get_or_create(topic_id, date)

        if quota.api_calls_used + amount > quota.api_calls_limit:
            return False

        quota.api_calls_used += amount
        self.session.flush()
        return True

    def get_remaining(self, topic_id: str, date: date) -> int:
        """获取剩余配额"""
        quota = self.get_or_create(topic_id, date)
        return max(0, quota.api_calls_limit - quota.api_calls_used)

    def reset_quota(self, topic_id: str, date: date, new_limit: int = 50) -> None:
        """重置配额"""
        quota = self.get_or_create(topic_id, date, new_limit)
        quota.api_calls_used = 0
        quota.api_calls_limit = new_limit
        quota.last_reset_at = datetime.now(UTC)
        self.session.flush()
