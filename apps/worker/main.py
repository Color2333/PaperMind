"""
PaperMind Worker - 定时任务调度（按主题独立调度）
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
            delay = base_delay * (2 ** attempt)
            logger.warning(
                "Attempt %d/%d failed: %s — retrying in %.0fs",
                attempt + 1, max_retries, e, delay,
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
            hour, weekday,
        )
        return

    logger.info(
        "topic_dispatch: triggering %d topic(s): %s",
        len(candidates),
        ", ".join(c["name"] for c in candidates),
    )
    for c in candidates:
        try:
            result = _retry_with_backoff(run_topic_ingest, c["id"], max_retries=_RETRY_MAX, base_delay=_RETRY_DELAY)
            logger.info(
                "topic %s done: inserted=%s, processed=%s",
                c["name"],
                result.get("inserted", 0),
                result.get("processed", 0),
            )
        except Exception:
            logger.exception("topic_dispatch failed for %s", c["name"])
    _write_heartbeat()


def brief_job() -> None:
    logger.info("Starting daily brief job")
    try:
        _retry_with_backoff(run_daily_brief, max_retries=_RETRY_MAX, base_delay=_RETRY_DELAY)
    except Exception:
        logger.exception("Daily brief job failed after retries")
    _write_heartbeat()


def weekly_graph_job() -> None:
    logger.info("Starting weekly graph job")
    try:
        _retry_with_backoff(run_weekly_graph_maintenance, max_retries=_RETRY_MAX, base_delay=_RETRY_DELAY)
    except Exception:
        logger.exception("Weekly graph job failed after retries")
    _write_heartbeat()


def run_worker() -> None:
    scheduler = BlockingScheduler(timezone="UTC")

    # 每整点检查主题调度
    scheduler.add_job(
        topic_dispatch_job,
        trigger=CronTrigger(minute=0),
        id="topic_dispatch",
        replace_existing=True,
    )

    # 每日简报（保持全局 cron）
    daily_trigger = CronTrigger.from_crontab(settings.daily_cron)
    scheduler.add_job(
        brief_job,
        trigger=daily_trigger,
        id="daily_brief",
        replace_existing=True,
    )

    # 每周图谱维护
    weekly_trigger = CronTrigger.from_crontab(settings.weekly_cron)
    scheduler.add_job(
        weekly_graph_job,
        trigger=weekly_trigger,
        id="weekly_graph",
        replace_existing=True,
    )

    def _graceful_stop(*_: object) -> None:
        stop_event.set()
        scheduler.shutdown(wait=False)

    signal.signal(signal.SIGINT, _graceful_stop)
    signal.signal(signal.SIGTERM, _graceful_stop)
    _write_heartbeat()
    logger.info("Worker started — hourly topic dispatch + daily brief + weekly graph")
    scheduler.start()


if __name__ == "__main__":
    run_worker()
