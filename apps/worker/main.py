"""
PaperMind Worker - 智能定时任务调度（UTC 时间 + 闲时处理）
@author Bamzc
@author Color2333
"""

from __future__ import annotations

import logging
import signal
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Event

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from packages.ai.daily_runner import (
    run_daily_brief,
    run_topic_ingest,
    run_weekly_graph_maintenance,
)
from packages.ai.idle_processor import start_idle_processor, stop_idle_processor
from packages.config import get_settings
from packages.logging_setup import setup_logging
from packages.storage.db import session_scope
from packages.storage.repositories import TopicRepository

setup_logging()
logger = logging.getLogger(__name__)

_HEALTH_FILE = Path("/tmp/worker_heartbeat")


def _write_heartbeat() -> None:
    """写入心跳文件供外部健康检查"""
    try:
        _HEALTH_FILE.write_text(str(time.time()))
    except OSError:
        pass


def _retry_with_backoff(fn, *args, max_retries: int = 3, base_delay: float = 5.0, **kwargs):
    """带指数退避的重试执行"""
    for attempt in range(max_retries):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            delay = base_delay * (2**attempt)
            logger.warning(
                "Attempt %d/%d failed: %s — retrying in %.0fs",
                attempt + 1,
                max_retries,
                e,
                delay,
            )
            time.sleep(delay)


settings = get_settings()
stop_event = Event()
_RETRY_MAX = settings.worker_retry_max
_RETRY_DELAY = settings.worker_retry_base_delay


def _should_run(freq: str, time_utc: int, hour: int, weekday: int) -> bool:
    """判断当前 UTC 小时是否匹配主题的调度规则"""
    if freq == "daily":
        return hour == time_utc
    if freq == "twice_daily":
        return hour == time_utc or hour == (time_utc + 12) % 24
    if freq == "weekdays":
        return hour == time_utc and weekday < 5
    if freq == "weekly":
        return hour == time_utc and weekday == 0
    return False


def topic_dispatch_job() -> None:
    """每小时执行：检查哪些主题需要在当前小时触发"""
    now = datetime.now(timezone.utc)
    hour = now.hour
    weekday = now.weekday()  # 0=Monday

    with session_scope() as session:
        topics = TopicRepository(session).list_topics(enabled_only=True)
        candidates = []
        for t in topics:
            freq = getattr(t, "schedule_frequency", "daily")
            time_utc = getattr(t, "schedule_time_utc", 21)
            if _should_run(freq, time_utc, hour, weekday):
                candidates.append({"id": t.id, "name": t.name})

    if not candidates:
        logger.info(
            "topic_dispatch: UTC %02d, weekday %d — no topics scheduled",
            hour,
            weekday,
        )
        return

    logger.info(
        "topic_dispatch: triggering %d topic(s): %s",
        len(candidates),
        ", ".join(c["name"] for c in candidates),
    )
    for c in candidates:
        try:
            result = _retry_with_backoff(
                run_topic_ingest, c["id"], max_retries=_RETRY_MAX, base_delay=_RETRY_DELAY
            )
            logger.info(
                "topic %s done: inserted=%s, processed=%s",
                c["name"],
                result.get("inserted", 0) if result else 0,
                result.get("processed", 0) if result else 0,
            )
        except Exception:
            logger.exception("topic_dispatch failed for %s", c["name"])
    _write_heartbeat()


def brief_job() -> None:
    """
    每日简报任务 - UTC 时间优化版

    时间表（UTC）：
    - 02:00 → 主题抓取论文
    - 02:00-04:00 → 并行处理论文（粗读 + 嵌入 + 精选精读）
    - 04:00 → 生成简报（包含所有处理完的论文）
    - 04:30 → 发送邮件（北京时间 12:30，午饭时间）
    """
    logger.info("📮 开始生成每日简报...")
    try:
        result = _retry_with_backoff(
            run_daily_brief, max_retries=_RETRY_MAX, base_delay=_RETRY_DELAY
        )
        logger.info(
            "✅ 每日简报生成完成：saved=%s, email_sent=%s",
            result.get("saved_path", "N/A") if result else "N/A",
            result.get("email_sent", False) if result else False,
        )
    except Exception:
        logger.exception("Daily brief job failed after retries")
    _write_heartbeat()


def weekly_graph_job() -> None:
    logger.info("Starting weekly graph job")
    try:
        _retry_with_backoff(
            run_weekly_graph_maintenance, max_retries=_RETRY_MAX, base_delay=_RETRY_DELAY
        )
    except Exception:
        logger.exception("Weekly graph job failed after retries")
    _write_heartbeat()


def run_worker() -> None:
    """
    Worker 主函数 - UTC 时间智能调度

    调度时间表（UTC）：
    ┌─────────────────────────────────────────────────────────┐
    │ 任务              │ 时间 (UTC)    │ 北京时间          │
    ├─────────────────────────────────────────────────────────┤
    │ 主题论文抓取      │ 02:00 每小时  │ 10:00 每小时       │
    │ 论文处理缓冲      │ 02:00-04:00   │ 10:00-12:00        │
    │ 每日简报生成      │ 04:00         │ 12:00              │
    │ 简报邮件发送      │ 04:30         │ 12:30 (午饭时间)   │
    │ 每周图谱维护      │ 22:00 周日    │ 周一 06:00         │
    │ 闲时自动处理      │ 全天检测      │ 全天检测           │
    └─────────────────────────────────────────────────────────┘
    """
    scheduler = BlockingScheduler(timezone="UTC")

    settings = get_settings()

    # 每整点检查主题调度（UTC 时间）
    scheduler.add_job(
        topic_dispatch_job,
        trigger=CronTrigger(minute=0),
        id="topic_dispatch",
        replace_existing=True,
    )
    logger.info("✅ 已添加：主题分发任务（每小时整点，UTC）")

    # 每日简报（UTC 4 点生成，4 点半发送）
    # 默认配置：DAILY_CRON=0 4 * * *
    daily_trigger = CronTrigger.from_crontab(getattr(settings, "daily_cron", "0 4 * * *"))
    scheduler.add_job(
        brief_job,
        trigger=daily_trigger,
        id="daily_brief",
        replace_existing=True,
    )
    logger.info(
        "✅ 已添加：每日简报任务（UTC %s，北京时间%s）",
        getattr(settings, "daily_cron", "0 4 * * *"),
        "12:00" if getattr(settings, "daily_cron", "").startswith("0 4") else "计算中",
    )

    # 每周图谱维护（UTC 周日 22 点 = 北京时间周一 6 点）
    weekly_trigger = CronTrigger.from_crontab(getattr(settings, "weekly_cron", "0 22 * * 0"))
    scheduler.add_job(
        weekly_graph_job,
        trigger=weekly_trigger,
        id="weekly_graph",
        replace_existing=True,
    )
    logger.info("✅ 已添加：每周图谱维护任务（UTC 周日 22:00）")

    # 优雅关闭
    def _graceful_stop(*_: object) -> None:
        logger.info("收到终止信号，正在关闭...")
        stop_event.set()
        stop_idle_processor()  # 停止闲时处理器
        scheduler.shutdown(wait=False)
        logger.info("Worker 已关闭")

    signal.signal(signal.SIGINT, _graceful_stop)
    signal.signal(signal.SIGTERM, _graceful_stop)

    # 写入初始心跳
    _write_heartbeat()

    # 启动闲时处理器
    logger.info("🤖 启动闲时自动处理器...")
    start_idle_processor()

    # 启动调度器
    logger.info("🚀 Worker 启动完成 - UTC 智能调度 + 闲时处理")
    logger.info("=" * 60)
    logger.info("调度时间表（UTC → 北京时间）:")
    logger.info("  • 主题抓取：每小时整点 → 每小时整点")
    logger.info("  • 每日简报：04:00 → 12:00")
    logger.info("  • 每周图谱：周日 22:00 → 周一 06:00")
    logger.info("  • 闲时处理：全天自动检测 → 全天自动检测")
    logger.info("=" * 60)

    scheduler.start()


if __name__ == "__main__":
    run_worker()
