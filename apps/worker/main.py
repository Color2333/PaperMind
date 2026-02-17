"""
PaperMind Worker - 定时任务调度（按主题独立调度）
@author Bamzc
"""
from __future__ import annotations

import logging
import signal
from datetime import datetime, timezone
from threading import Event

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from packages.ai.daily_runner import (
    run_daily_brief,
    run_topic_ingest,
    run_weekly_graph_maintenance,
)
from packages.config import get_settings
from packages.storage.db import session_scope
from packages.storage.repositories import TopicRepository

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()
stop_event = Event()


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
            result = run_topic_ingest(c["id"])
            logger.info(
                "topic %s done: inserted=%s, processed=%s",
                c["name"],
                result.get("inserted", 0),
                result.get("processed", 0),
            )
        except Exception:
            logger.exception("topic_dispatch failed for %s", c["name"])


def brief_job() -> None:
    logger.info("Starting daily brief job")
    run_daily_brief()


def weekly_graph_job() -> None:
    logger.info("Starting weekly graph job")
    run_weekly_graph_maintenance()


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
    logger.info("Worker started — hourly topic dispatch + daily brief + weekly graph")
    scheduler.start()


if __name__ == "__main__":
    run_worker()
