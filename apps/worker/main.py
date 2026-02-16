"""
PaperMind Worker - 定时任务调度
@author Bamzc
"""
from __future__ import annotations

import logging
import signal
from threading import Event

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from packages.ai.daily_runner import (
    run_daily_brief,
    run_daily_ingest,
    run_weekly_graph_maintenance,
)
from packages.config import get_settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

settings = get_settings()
stop_event = Event()


def ingest_job() -> None:
    logger.info("Starting daily ingest job")
    run_daily_ingest()


def brief_job() -> None:
    logger.info("Starting daily brief job")
    run_daily_brief()


def weekly_graph_job() -> None:
    logger.info("Starting weekly graph job")
    run_weekly_graph_maintenance()


def run_worker() -> None:
    scheduler = BlockingScheduler(timezone="UTC")
    daily_trigger = CronTrigger.from_crontab(settings.daily_cron)
    weekly_trigger = CronTrigger.from_crontab(
        settings.weekly_cron
    )
    scheduler.add_job(
        ingest_job,
        trigger=daily_trigger,
        id="daily_ingest",
        replace_existing=True,
    )
    scheduler.add_job(
        brief_job,
        trigger=daily_trigger,
        id="daily_brief",
        replace_existing=True,
    )
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
    logger.info("Worker started, awaiting scheduled jobs")
    scheduler.start()


if __name__ == "__main__":
    run_worker()
