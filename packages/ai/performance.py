"""
性能监控工具
@author Color2333
"""
from __future__ import annotations

import functools
import logging
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")

logger = logging.getLogger(__name__)


@dataclass
class PerformanceMetrics:
    """性能指标"""

    name: str
    duration_ms: float
    success: bool
    error: str | None = None
    metadata: dict | None = None


class PerformanceMonitor:
    """
    性能监控器 - 用于追踪函数执行时间和性能
    """

    def __init__(self):
        self._metrics: list[PerformanceMetrics] = []

    def record(
        self,
        name: str,
        duration_ms: float,
        success: bool = True,
        error: str | None = None,
        metadata: dict | None = None,
    ):
        """记录性能指标"""
        self._metrics.append(
            PerformanceMetrics(
                name=name,
                duration_ms=duration_ms,
                success=success,
                error=error,
                metadata=metadata,
            )
        )

    def get_metrics(self, name: str | None = None) -> list[PerformanceMetrics]:
        """获取性能指标"""
        if name:
            return [m for m in self._metrics if m.name == name]
        return self._metrics.copy()

    def get_average_duration(self, name: str) -> float | None:
        """获取平均执行时间"""
        metrics = self.get_metrics(name)
        if not metrics:
            return None
        return sum(m.duration_ms for m in metrics) / len(metrics)

    def get_slowest(self, name: str, limit: int = 10) -> list[PerformanceMetrics]:
        """获取最慢的执行记录"""
        metrics = self.get_metrics(name)
        return sorted(metrics, key=lambda m: m.duration_ms, reverse=True)[:limit]

    def clear(self):
        """清空记录"""
        self._metrics.clear()

    def print_summary(self):
        """打印性能摘要"""
        if not self._metrics:
            logger.info("No performance metrics recorded")
            return

        # 按名称分组
        grouped: dict[str, list[PerformanceMetrics]] = {}
        for metric in self._metrics:
            grouped.setdefault(metric.name, []).append(metric)

        logger.info("=" * 60)
        logger.info("Performance Summary")
        logger.info("=" * 60)

        for name, metrics in sorted(grouped.items()):
            total = len(metrics)
            success = sum(1 for m in metrics if m.success)
            avg_duration = sum(m.duration_ms for m in metrics) / total
            max_duration = max(m.duration_ms for m in metrics)

            logger.info(
                f"{name}: {total} calls, "
                f"{success}/{total} success, "
                f"avg {avg_duration:.2f}ms, "
                f"max {max_duration:.2f}ms"
            )

        logger.info("=" * 60)


# 全局性能监控器实例
_global_monitor = PerformanceMonitor()


def get_global_monitor() -> PerformanceMonitor:
    """获取全局性能监控器"""
    return _global_monitor


def track_performance(name: str | None = None):
    """
    装饰器：追踪函数执行性能

    Usage:
        @track_performance("database_query")
        def query_users():
            ...
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        func_name = name or func.__name__

        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            start_time = time.perf_counter()
            success = True
            error = None

            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                success = False
                error = str(e)
                raise
            finally:
                duration_ms = (time.perf_counter() - start_time) * 1000
                _global_monitor.record(
                    name=func_name,
                    duration_ms=duration_ms,
                    success=success,
                    error=error,
                )

        return wrapper

    return decorator


@contextmanager
def performance_context(name: str):
    """
    上下文管理器：追踪代码块执行性能

    Usage:
        with performance_context("data_processing"):
            process_data()
    """

    start_time = time.perf_counter()
    success = True
    error = None

    try:
        yield
    except Exception as e:
        success = False
        error = str(e)
        raise
    finally:
        duration_ms = (time.perf_counter() - start_time) * 1000
        _global_monitor.record(
            name=name,
            duration_ms=duration_ms,
            success=success,
            error=error,
        )


def log_slow_queries(
    threshold_ms: float = 1000.0,
    logger_instance: logging.Logger | None = None,
):
    """
    装饰器：记录慢查询

    Args:
        threshold_ms: 慢查询阈值（毫秒）
        logger_instance: 自定义 logger

    Usage:
        @log_slow_queries(threshold_ms=500)
        def expensive_operation():
            ...
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            start_time = time.perf_counter()
            result = func(*args, **kwargs)
            duration_ms = (time.perf_counter() - start_time) * 1000

            if duration_ms > threshold_ms:
                log = logger_instance or logger
                log.warning(
                    f"Slow query detected: {func.__name__} "
                    f"took {duration_ms:.2f}ms "
                    f"(threshold: {threshold_ms:.2f}ms)"
                )

            return result

        return wrapper

    return decorator


def async_track_performance(name: str | None = None):
    """
    装饰器：追踪异步函数执行性能

    Usage:
        @async_track_performance("async_api_call")
        async def fetch_data():
            ...
    """

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        func_name = name or func.__name__

        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            start_time = time.perf_counter()
            success = True
            error = None

            try:
                result = await func(*args, **kwargs)  # type: ignore
                return result
            except Exception as e:
                success = False
                error = str(e)
                raise
            finally:
                duration_ms = (time.perf_counter() - start_time) * 1000
                _global_monitor.record(
                    name=func_name,
                    duration_ms=duration_ms,
                    success=success,
                    error=error,
                )

        return wrapper

    return decorator
