"""
API 并发控制器 - 智能限流 + 动态并发
@author Color2333
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from threading import Lock
from typing import Optional

from packages.config import get_settings

logger = logging.getLogger(__name__)


class TokenBucket:
    """令牌桶算法实现"""

    def __init__(self, rate: float = 10.0, capacity: int = 20):
        """
        Args:
            rate: 令牌生成速率 (个/秒)
            capacity: 桶容量 (最大令牌数)
        """
        self.rate = rate
        self.capacity = capacity
        self.tokens = float(capacity)
        self.last_update = time.time()
        self._lock = Lock()

    def acquire(self, tokens: int = 1, timeout: Optional[float] = None) -> bool:
        """获取令牌

        Args:
            tokens: 需要获取的令牌数
            timeout: 超时时间 (秒)，None 表示无限等待

        Returns:
            bool: 是否成功获取
        """
        start_time = time.time()

        while True:
            with self._lock:
                now = time.time()
                # 补充令牌
                elapsed = now - self.last_update
                self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
                self.last_update = now

                # 尝试获取
                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return True

            # 检查超时
            if timeout is not None and (time.time() - start_time) >= timeout:
                return False

            # 等待一小段时间再试
            time.sleep(0.1)

    def get_available_tokens(self) -> float:
        """获取当前可用令牌数"""
        with self._lock:
            now = time.time()
            elapsed = now - self.last_update
            return min(self.capacity, self.tokens + elapsed * self.rate)


class APIRateLimiter:
    """
    智能 API 并发控制器

    功能:
    - 动态并发：根据时间段调整并发数
    - 请求冷却：每次调用后短暂等待，避免触发限流
    - 429 自动降速：遇到限流自动降低速率
    - 多 API 支持：LLM、ArXiv、Semantic Scholar 独立限流
    """

    # 时间段配置 (UTC 时间)
    TIME_SLOTS = [
        # (start_hour, end_hour, max_concurrency, rate)
        (0, 8, 5, 10.0),  # 深夜闲时：高并发
        (8, 12, 2, 5.0),  # 上午工作：保守
        (12, 14, 3, 7.0),  # 午休时间：适度
        (14, 18, 2, 5.0),  # 下午工作：保守
        (18, 22, 3, 7.0),  # 晚间时间：适度
        (22, 24, 5, 10.0),  # 深夜闲时：高并发
    ]

    def __init__(self):
        self.settings = get_settings()

        # 初始化令牌桶（多个 API 独立限流）
        self._buckets = {
            "llm": TokenBucket(rate=5.0, capacity=10),
            "arxiv": TokenBucket(rate=2.0, capacity=5),
            "embedding": TokenBucket(rate=3.0, capacity=8),
            "vision": TokenBucket(rate=1.0, capacity=3),
        }

        # 当前并发配置
        self._current_slot = self._get_current_time_slot()
        self._max_concurrency = self._current_slot[2]
        self._active_tasks = 0
        self._lock = Lock()

        # 429 错误计数（自动降速）
        self._rate_limit_errors = 0
        self._last_error_time = 0

    def _get_current_time_slot(self) -> tuple:
        """获取当前时间段配置"""
        now = datetime.now(timezone.utc)
        hour = now.hour

        for start, end, concurrency, rate in self.TIME_SLOTS:
            if start <= hour < end:
                return (start, end, concurrency, rate)

        # 默认配置
        return (0, 8, 5, 10.0)

    def _update_time_slot(self):
        """检查并更新时间段配置"""
        current_slot = self._get_current_time_slot()

        if current_slot != self._current_slot:
            self._current_slot = current_slot
            self._max_concurrency = current_slot[2]

            # 更新令牌桶速率
            new_rate = current_slot[3]
            for bucket in self._buckets.values():
                bucket.rate = new_rate

            logger.info(
                "切换到时间段配置 [%02d:00-%02d:00]: 并发=%d, 速率=%.1f/s",
                current_slot[0],
                current_slot[1],
                current_slot[2],
                current_slot[3],
            )

    def can_start_task(self) -> bool:
        """检查是否可以启动新任务"""
        self._update_time_slot()

        with self._lock:
            return self._active_tasks < self._max_concurrency

    def start_task(self) -> bool:
        """尝试启动任务

        Returns:
            bool: 是否成功启动
        """
        self._update_time_slot()

        with self._lock:
            if self._active_tasks < self._max_concurrency:
                self._active_tasks += 1
                return True
            return False

    def end_task(self):
        """任务结束"""
        with self._lock:
            if self._active_tasks > 0:
                self._active_tasks -= 1

    def acquire(self, api_type: str = "llm", timeout: Optional[float] = None) -> bool:
        """获取 API 调用许可

        Args:
            api_type: API 类型 (llm/arxiv/embedding/vision)
            timeout: 超时时间 (秒)

        Returns:
            bool: 是否成功获取
        """
        if api_type not in self._buckets:
            logger.warning(f"未知的 API 类型：{api_type}")
            api_type = "llm"

        bucket = self._buckets[api_type]

        # 等待可用令牌
        acquired = bucket.acquire(tokens=1, timeout=timeout)

        if acquired:
            # 冷却时间（避免过于频繁）
            cooldown = 1.0 / self._current_slot[3]
            time.sleep(cooldown)

        return acquired

    def record_rate_limit_error(self):
        """记录 429 限流错误，自动降速"""
        now = time.time()

        # 5 分钟内多次限流，降低速率
        if now - self._last_error_time < 300:
            self._rate_limit_errors += 1

            if self._rate_limit_errors >= 3:
                # 严重限流，速率减半
                for bucket in self._buckets.values():
                    bucket.rate = max(0.5, bucket.rate * 0.5)

                logger.warning("检测到频繁限流，速率降至 %.1f/s", bucket.rate)
                self._rate_limit_errors = 0
        else:
            self._rate_limit_errors = 1

        self._last_error_time = now

    def get_status(self) -> dict:
        """获取当前状态"""
        self._update_time_slot()

        return {
            "time_slot": f"{self._current_slot[0]:02d}:00 - {self._current_slot[1]:02d}:00 (UTC)",
            "max_concurrency": self._max_concurrency,
            "active_tasks": self._active_tasks,
            "available_slots": self._max_concurrency - self._active_tasks,
            "buckets": {
                name: f"{bucket.get_available_tokens():.1f}/{bucket.capacity}"
                for name, bucket in self._buckets.items()
            },
            "current_rate": f"{self._current_slot[3]:.1f} req/s",
        }


# 全局单例
_global_limiter: Optional[APIRateLimiter] = None
_limiter_lock = Lock()


def get_rate_limiter() -> APIRateLimiter:
    """获取全局速率限制器实例"""
    global _global_limiter

    if _global_limiter is None:
        with _limiter_lock:
            if _global_limiter is None:
                _global_limiter = APIRateLimiter()

    return _global_limiter


def acquire_api(api_type: str = "llm", timeout: Optional[float] = 10.0) -> bool:
    """便捷函数：获取 API 调用许可

    Args:
        api_type: API 类型
        timeout: 超时时间

    Returns:
        bool: 是否成功获取
    """
    limiter = get_rate_limiter()
    return limiter.acquire(api_type, timeout)


def can_start_task() -> bool:
    """便捷函数：检查是否可以启动任务"""
    return get_rate_limiter().can_start_task()
