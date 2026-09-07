"""
PaperMind Worker - 定时调度 + Executor 宿主（C3/C6/C11 退出口）

职责边界（设计③「Scheduler 不直接执行业务」）：
- APScheduler 只按时间提交 durable Job（submit_job），不运行研究逻辑；
- 内置 Executor 宿主（ExecutorRunner）经 Go Core 领取并执行 Task——
  与独立 executor 进程同一执行路径（CORE_ADDR 未配置时仅调度不执行）；
- batch_jobs 消费者已退役（C11）：批处理入口全部走 durable
  ProcessUnreadBatch / batch_process_unread 任务；
- 心跳语义 = 调度存活 + 提交成功；业务结果由 durable Job/Task 状态承载。
"""

from __future__ import annotations

import contextlib
import logging
import os
import signal
import time
from pathlib import Path
from threading import Event

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from packages.ai.idle_processor import (
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


def _submit_durable(*, kind: str, capability: str, title: str, input_ref=None) -> str | None:
    """调度触发点：提交 durable Job（不执行）；失败写心跳错误供 status 页呈现"""
    from packages.application.commands.jobs import submit_job

    try:
        submitted = submit_job(
            kind=kind,
            capability=capability,
            title=title,
            input_ref=input_ref or {},
            created_by="worker",
        )
        logger.info("已提交 %s（task=%s）", kind, submitted["task_id"][:8])
        return submitted["task_id"]
    except Exception as exc:
        logger.exception("提交 %s 失败", kind)
        _write_heartbeat(error=f"submit {kind} failed: {exc}")
        return None


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
    """每小时：按订阅计划提交主题抓取任务（业务在 Executor 侧执行）"""

    # 计划判断逻辑（哪些主题本小时到期）作为 handler 一部分执行；
    # 调度器只按小时提交 topic_dispatch 任务，由 handler 计算到期主题并逐个抓取
    _submit_durable(
        kind="TopicDispatch",
        capability="topic_dispatch",
        title="⏰ 主题调度抓取",
    )
    _write_heartbeat()


def brief_job() -> None:
    """每日简报：提交 durable 任务（每日 cron；时间来自 DailyReportConfig）"""
    _submit_durable(
        kind="RunDailyBrief",
        capability="daily_brief_publish",
        title="📮 每日简报生成",
    )
    _write_heartbeat()


def weekly_graph_job() -> None:
    """每周图谱维护：提交 durable 任务"""
    _submit_durable(
        kind="RunWeeklyGraph",
        capability="weekly_graph_maintenance",
        title="🔄 每周图谱维护",
    )
    _write_heartbeat()


def cs_feed_dispatch_job():
    """每小时 CS 分类同步 + 订阅抓取：提交 durable 任务"""
    _submit_durable(
        kind="CSFeedDispatch",
        capability="cs_feed_dispatch",
        title="📚 CS 分类订阅调度",
    )
    _write_heartbeat()


# ---------- Executor 宿主（C7：与独立 executor 进程同一执行路径） ----------

_executor_runner = None
_executor_thread = None


def _start_executor_host(core_addr: str) -> None:
    """在 worker 进程内启动 ExecutorRunner（经 Go Core 领取执行）"""
    global _executor_runner, _executor_thread

    from packages.application.commands.task_registry import TASK_CAPABILITIES
    from packages.core_client.client import CoreClient
    from packages.executor_runtime.runner import (
        ExecutorConfig,
        ExecutorRunner,
        handlers_from_registry,
    )

    # 领取集合按 trigger 语义（executor=worker 执行）；manual_recovery 只影响
    # 重试策略（失败不自动重试），不再排除领取——此前邮件/日报三项被误排除成悬空
    capabilities = [name for name, spec in TASK_CAPABILITIES.items() if spec.trigger == "executor"]
    handlers = handlers_from_registry(capabilities)
    client = CoreClient(
        f"http://{core_addr}",
        token=os.environ.get("CORE_TOKEN", ""),
    )
    _executor_runner = ExecutorRunner(
        client=client,
        config=ExecutorConfig(
            executor_id=os.environ.get("WORKER_EXECUTOR_ID", f"worker-{os.getpid()}"),
            capabilities=capabilities,
            poll_interval_s=1.0,
            heartbeat_interval_s=15.0,
        ),
        handlers=handlers,
    )
    _executor_thread = _executor_runner.run_in_thread()
    logger.info("⚙️ Executor 宿主已启动：%d 项能力 → %s", len(capabilities), core_addr)


def _stop_executor_host() -> None:
    global _executor_runner, _executor_thread
    if _executor_runner is None:
        return
    _executor_runner.drain()
    if _executor_thread is not None:
        _executor_thread.join(timeout=30)
    logger.info("Executor 宿主已停止")


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

    # 工作流"任务完成后展开"轮询（此前 expand_job 只在提交时执行一次——
    # 多阶段工作流后续阶段永远不 spawn）
    def _expand_workflows() -> None:
        from packages.application.commands.workflows import expand_due_workflow_jobs

        try:
            with session_scope() as session:
                created = expand_due_workflow_jobs(session)
            if created:
                logger.info("🔁 工作流补展开：%d 个新 Task", created)
        except Exception:
            logger.exception("工作流补展开失败")

    scheduler.add_job(
        _expand_workflows,
        trigger="interval",
        seconds=15,
        id="expand_workflows",
        **_job_kwargs,
    )
    logger.info("✅ 已添加：工作流补展开轮询（每 15s）")

    # 优雅关闭（High 3f：等待进行中任务跑完，避免已下载 PDF 未 set_pdf_path
    # 的中间态丢失；wait=True + 60s 超时兜底）
    def _graceful_stop(*_: object) -> None:
        logger.info("收到终止信号，正在关闭...")
        stop_event.set()
        stop_idle_processor()  # 停止闲时处理器
        _stop_executor_host()
        scheduler.shutdown(wait=True)
        logger.info("Worker 已关闭")

    signal.signal(signal.SIGINT, _graceful_stop)
    signal.signal(signal.SIGTERM, _graceful_stop)

    # 写入初始心跳
    _write_heartbeat()

    # 启动闲时处理器（空闲时提交 durable 批处理任务——不直接执行）
    logger.info("🤖 启动闲时自动处理器...")
    start_idle_processor()

    # C11 退出口：batch_jobs 消费者已删除——批处理入口全部走 durable 任务，
    # 由下方 Executor 宿主（或独立 executor 进程）执行。
    # C7：worker 兼 Executor 宿主——与独立 executor 进程同一执行路径。
    core_addr = os.environ.get("CORE_ADDR", "")
    if core_addr:
        _start_executor_host(core_addr)
    else:
        logger.warning(
            "CORE_ADDR 未配置——worker 仅调度提交，不执行任务（执行由独立 executor 进程承担）"
        )

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
