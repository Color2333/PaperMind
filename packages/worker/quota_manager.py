import logging
from datetime import date

from packages.storage.db import session_scope
from packages.storage.models import IeeeApiQuota, TopicSubscription

logger = logging.getLogger(__name__)


class QuotaManager:
    """IEEE API配额管理器"""

    @staticmethod
    def check_quota(topic_id: str, needed: int = 1) -> bool:
        """检查主题是否有足够的 IEEE 配额"""
        with session_scope() as session:
            topic = session.get(TopicSubscription, topic_id)
            if not topic:
                return True

            if "ieee" not in (topic.sources or []):
                return True

            if topic.ieee_daily_quota <= 0:
                return False

            today = date.today()
            quota_record = (
                session.query(IeeeApiQuota)
                .filter_by(topic_id=topic_id, date=today)
                .first()
            )

            if not quota_record:
                return topic.ieee_daily_quota >= needed

            remaining = quota_record.api_calls_limit - quota_record.api_calls_used
            return remaining >= needed

    @staticmethod
    def reserve_quota(topic_id: str, count: int = 1) -> bool:
        """预占配额（不实际消耗，只是检查是否足够）"""
        return QuotaManager.check_quota(topic_id, count)

    @staticmethod
    def consume_quota(topic_id: str, count: int = 1) -> bool:
        """实际消耗配额"""
        with session_scope() as session:
            topic = session.get(TopicSubscription, topic_id)
            if not topic:
                return True

            if "ieee" not in (topic.sources or []):
                return True

            today = date.today()
            quota_record = (
                session.query(IeeeApiQuota)
                .filter_by(topic_id=topic_id, date=today)
                .first()
            )

            if not quota_record:
                quota_record = IeeeApiQuota(
                    topic_id=topic_id,
                    date=today,
                    api_calls_used=0,
                    api_calls_limit=topic.ieee_daily_quota,
                )
                session.add(quota_record)

            if quota_record.api_calls_used + count > quota_record.api_calls_limit:
                return False

            quota_record.api_calls_used += count
            return True

    @staticmethod
    def get_remaining(topic_id: str) -> int:
        """获取主题剩余的 IEEE 配额"""
        with session_scope() as session:
            topic = session.get(TopicSubscription, topic_id)
            if not topic:
                return 0

            if "ieee" not in (topic.sources or []):
                return 0

            today = date.today()
            quota_record = (
                session.query(IeeeApiQuota)
                .filter_by(topic_id=topic_id, date=today)
                .first()
            )

            if not quota_record:
                return topic.ieee_daily_quota

            return max(0, quota_record.api_calls_limit - quota_record.api_calls_used)

    @staticmethod
    def is_channel_enabled(topic_id: str, channel: str) -> bool:
        """检查主题是否启用了某渠道"""
        if channel != "ieee":
            return True

        with session_scope() as session:
            topic = session.get(TopicSubscription, topic_id)
            if not topic:
                return True

            sources = topic.sources or []
            if channel not in sources:
                return True

            remaining = QuotaManager.get_remaining(topic_id)
            return remaining > 0

    @staticmethod
    def filter_channels_by_quota(topic_id: str, channels: list[str]) -> list[str]:
        """过滤掉没有配额的渠道"""
        result = []
        for ch in channels:
            if ch == "ieee" and not QuotaManager.check_quota(topic_id):
                logger.debug("IEEE quota exhausted for topic %s, skipping", topic_id)
                continue
            result.append(ch)
        return result

    @staticmethod
    def reset_quota(topic_id: str) -> None:
        """重置主题的 IEEE 配额（用于测试或手动重置）"""
        with session_scope() as session:
            topic = session.get(TopicSubscription, topic_id)
            if not topic:
                return

            if "ieee" not in (topic.sources or []):
                return

            today = date.today()
            quota_record = (
                session.query(IeeeApiQuota)
                .filter_by(topic_id=topic_id, date=today)
                .first()
            )

            if quota_record:
                quota_record.api_calls_used = 0
                logger.info("IEEE quota reset for topic %s", topic_id)
