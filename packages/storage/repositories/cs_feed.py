"""
arXiv CS 分类订阅数据仓储
@author Color2333
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from packages.storage.models import CSCategory, CSFeedSubscription


class CSFeedRepository:
    """arXiv CS 分类订阅 Repository"""

    def __init__(self, session: Session):
        self.session = session

    def get_categories(self) -> list[CSCategory]:
        return list(self.session.execute(select(CSCategory)).scalars())

    def upsert_category(self, code: str, name: str, description: str = "") -> CSCategory:
        existing = self.session.execute(
            select(CSCategory).where(CSCategory.code == code)
        ).scalar_one_or_none()
        if existing:
            existing.name = name
            existing.description = description
            existing.cached_at = datetime.now(UTC)
            return existing
        cat = CSCategory(code=code, name=name, description=description)
        self.session.add(cat)
        self.session.commit()
        return cat

    def get_subscriptions(self) -> list[CSFeedSubscription]:
        return list(self.session.execute(select(CSFeedSubscription)).scalars())

    def get_subscription(self, category_code: str) -> CSFeedSubscription | None:
        return self.session.execute(
            select(CSFeedSubscription).where(CSFeedSubscription.category_code == category_code)
        ).scalar_one_or_none()

    def upsert_subscription(
        self, category_code: str, daily_limit: int, enabled: bool = True
    ) -> CSFeedSubscription:
        existing = self.get_subscription(category_code)
        if existing:
            existing.daily_limit = daily_limit
            existing.enabled = enabled
            self.session.commit()
            return existing
        sub = CSFeedSubscription(
            category_code=category_code, daily_limit=daily_limit, enabled=enabled
        )
        self.session.add(sub)
        self.session.commit()
        return sub

    def delete_subscription(self, category_code: str) -> bool:
        sub = self.get_subscription(category_code)
        if sub:
            self.session.delete(sub)
            self.session.commit()
            return True
        return False

    def update_run_status(self, category_code: str, count: int):
        sub = self.get_subscription(category_code)
        if sub:
            now = datetime.now(UTC)
            # 修 daily_limit 失效 bug：此前 last_run_count = count（覆盖），当日多次抓取会重置配额，
            # 绕过 daily_limit。改累加；跨天先清零，避免昨天余量带进今天
            if sub.last_run_at is not None and sub.last_run_at.date() != now.date():
                sub.last_run_count = 0
            sub.last_run_at = now
            sub.last_run_count = (sub.last_run_count or 0) + count
            sub.status = "active"
            self.session.commit()

    def set_cool_down(self, category_code: str, until: datetime):
        sub = self.get_subscription(category_code)
        if sub:
            sub.status = "cool_down"
            sub.cool_down_until = until
            self.session.commit()

    def get_active_subscriptions(self) -> list[CSFeedSubscription]:
        return list(
            self.session.execute(
                select(CSFeedSubscription).where(CSFeedSubscription.enabled.is_(True))
            ).scalars()
        )
