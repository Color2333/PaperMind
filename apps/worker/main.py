"""
PaperMind Worker - 智能定时任务调度（UTC 时间 + 闲时处理）
@author Color2333
@author Color2333
"""

from __future__ import annotations

import contextlib
import logging
import signal
import time
from datetime import UTC, datetime
from pathlib import Path
from threading import Event

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from packages.ai.cs_feed_orchestrator import CSFeedOrchestrator
from packages.ai.daily_runner import (
    run_daily_brief,
    run_topic_ingest,
    run_weekly_graph_maintenance,
)
from packages.ai.idle_processor import (
    set_dispatching,
    start_idle_processor,
    stop_idle_processor,
)
from packages.config import get_settings
from packages.logging_setup import setup_logging
from packages.storage.db import session_scope
from packages.storage.repositories import TopicRepository

setup_logging()
logger = logging.getLogger(__name__)

# 心跳改写共享卷 pm_data（/app/data），backend 也能读同一文件暴露 worker 状态。
# status 页（/system/worker 端点 + Operations 面板）读此文件展示 worker 健康。
_HEALTH_FILE = Path("/app/data/worker_heartbeat.json")
# 心跳健康判定：最近一次心跳距现在超过此秒数视为不健康（status 页展示用）
_HEARTBEAT_STALE_SECONDS = 1200  # 20 分钟


def _write_heartbeat(error: str | None = None) -> None:
    """写入心跳文件供 status 页查询（记录最近一次错误，不再掩盖故障）。

    写入 JSON {ts, error}：status 页读 ts 判定时效，error 字段记录最近致命错误。
    job 全部失败时不写心跳（让心跳自然过期 → status 页反映故障）。
    """
    import json

    with contextlib.suppress(OSError):
        _HEALTH_FILE.write_text(
            json.dumps({"ts": time.time(), "error": error[:200] if error else None})
        )


def _read_heartbeat() -> dict | None:
    """读共享卷心跳文件，供 status 端点查询。文件缺失/损坏返回 None。"""
    import json

    try:
        return json.loads(_HEALTH_FILE.read_text())
    except (OSError, ValueError, TypeError):
        return None


def _update_topic_run_status(topic_id: str, *, error: str | None) -> None:
    """记录主题抓取的最近运行时间与错误（Critical #4：失败可查可补抓）。

    抓取失败此前静默无痕，定位不到出问题的主题。这里在每次抓取后持久化
    last_run_at / last_error，失败信息入库便于排查与补抓。
    """
    try:
        with session_scope() as session:
            TopicRepository(session).update_run_status(topic_id, error=error)
    except Exception:
        logger.exception("Failed to persist topic run status for %s", topic_id)


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

cs_orchestrator = CSFeedOrchestrator()


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
    now = datetime.now(UTC)
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
    # High 2d：置调度标志，idle_processor 检测到即视为繁忙，避免抢同一批论文重复处理
    # High 2e：全部失败不写 heartbeat，让心跳自然过期 → healthcheck 反映故障
    set_dispatching(True)
    failures: list[str] = []
    try:
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
                _update_topic_run_status(c["id"], error=None)
            except Exception as e:
                logger.exception("topic_dispatch failed for %s", c["name"])
                _update_topic_run_status(c["id"], error=str(e))
                failures.append(f"{c['name']}: {e}")
    finally:
        set_dispatching(False)
    if not failures:
        _write_heartbeat()
    else:
        # 全部失败时不写健康心跳，仅记录致命错误到日志（healthcheck 靠时效捕获）
        logger.error("topic_dispatch 全部失败，跳过心跳写入：%s", failures)


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
    except Exception as e:
        # High 2e：失败不写心跳，让健康检查靠时效捕获故障
        logger.exception("Daily brief job failed after retries: %s", e)
        return
    _write_heartbeat()


def weekly_graph_job() -> None:
    logger.info("Starting weekly graph job")
    try:
        _retry_with_backoff(
            run_weekly_graph_maintenance, max_retries=_RETRY_MAX, base_delay=_RETRY_DELAY
        )
    except Exception as e:
        # High 2e：失败不写心跳
        logger.exception("Weekly graph job failed after retries: %s", e)
        return
    _write_heartbeat()


def cs_feed_dispatch_job():
    """每小时同步分类 + 执行订阅抓取（High 2e：失败不写心跳）"""
    try:
        cs_orchestrator.sync_categories()
        cs_orchestrator.run()
    except Exception as e:
        logger.exception("cs_feed_dispatch failed: %s", e)
        return
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
    # High 3e：显式配置 max_instances / misfire_grace_time / coalesce，避免
    # 重复触发与 misfire 丢失；用 apscheduler 的 ThreadPoolExecutor(max_workers=3)
    # 替代默认单线程池，允许 topic_dispatch / cs_feed / brief 适度并发
    from apscheduler.executors.pool import ThreadPoolExecutor as APSThreadPoolExecutor

    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_executor(APSThreadPoolExecutor(max_workers=3))

    # 公共 job 配置：单实例 + 5 分钟 misfire 容忍 + 合并错过的触发
    _job_kwargs = {
        "max_instances": 1,
        "misfire_grace_time": 300,
        "coalesce": True,
        "replace_existing": True,
    }

    settings = get_settings()

    # 每整点检查主题调度（UTC 时间）—— 整点第 0 分钟
    scheduler.add_job(
        topic_dispatch_job,
        trigger=CronTrigger(minute=0),
        id="topic_dispatch",
        **_job_kwargs,
    )
    logger.info("✅ 已添加：主题分发任务（每小时整点，UTC）")

    # CS 分类订阅调度 —— 错开 5 分钟，避免与 topic_dispatch 同分钟抢线程
    scheduler.add_job(
        cs_feed_dispatch_job,
        trigger=CronTrigger(minute=5),
        id="cs_feed_dispatch",
        **_job_kwargs,
    )
    logger.info("✅ 已添加：CS分类订阅调度任务（每小时 :05，UTC）")

    # 每日简报（从数据库读取 cron 表达式）
    from packages.storage.db import session_scope
    from packages.storage.repositories import DailyReportConfigRepository

    try:
        with session_scope() as session:
            config = DailyReportConfigRepository(session).get_config()
            daily_cron = config.cron_expression or "0 4 * * *"
    except Exception as e:
        logger.warning(f"从数据库读取 cron 失败：{e}，使用默认值")
        daily_cron = "0 4 * * *"

    daily_trigger = CronTrigger.from_crontab(daily_cron)
    scheduler.add_job(
        brief_job,
        trigger=daily_trigger,
        id="daily_brief",
        **_job_kwargs,
    )
    logger.info(
        "✅ 已添加：每日简报任务（cron: %s）",
        daily_cron,
    )

    # 每周图谱维护（UTC 周日 22 点 = 北京时间周一 6 点）
    weekly_trigger = CronTrigger.from_crontab(getattr(settings, "weekly_cron", "0 22 * * 0"))
    scheduler.add_job(
        weekly_graph_job,
        trigger=weekly_trigger,
        id="weekly_graph",
        **_job_kwargs,
    )
    logger.info("✅ 已添加：每周图谱维护任务（UTC 周日 22:00）")

    # 优雅关闭（High 3f：等待进行中任务跑完，避免已下载 PDF 未 set_pdf_path
    # 的中间态丢失；wait=True + 60s 超时兜底）
    def _graceful_stop(*_: object) -> None:
        logger.info("收到终止信号，正在关闭...")
        stop_event.set()
        stop_idle_processor()  # 停止闲时处理器
        scheduler.shutdown(wait=True)
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
