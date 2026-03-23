import logging

from packages.storage.db import session_scope
from packages.storage.models import TopicSubscription

logger = logging.getLogger(__name__)


class QuotaManager:
    """IEEE API配额管理器"""

    @staticmethod
    def check_quota(topic_id: str, needed: int = 1) -> bool:
        """检查主题是否有足够的IEEE配额"""
        with session_scope() as session:
            topic = session.get(TopicSubscription, topic_id)
            if not topic:
                return True

            if "ieee" not in (topic.sources or []):
                return True

            if topic.ieee_daily_quota <= 0:
                return False

            remaining = topic.ieee_daily_quota
            return remaining >= needed

    @staticmethod
    def reserve_quota(topic_id: str, count: int = 1) -> bool:
        """预占配额（不实际消耗，只是检查是否足够）"""
        return QuotaManager.check_quota(topic_id, count)

    @staticmethod
    def get_remaining(topic_id: str) -> int:
        """获取主题剩余的IEEE配额"""
        with session_scope() as session:
            topic = session.get(TopicSubscription, topic_id)
            if not topic:
                return 0

            if "ieee" not in (topic.sources or []):
                return 0

            return max(0, topic.ieee_daily_quota)

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
            return channel in sources and topic.ieee_daily_quota > 0

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
