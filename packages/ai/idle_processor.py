"""
闲时自动处理器 - 检测系统空闲状态，自动批量处理未读论文
@author Color2333
"""

from __future__ import annotations

import logging
import time
from threading import Event, Thread

from sqlalchemy import select

from packages.config import get_settings
from packages.storage.db import session_scope
from packages.storage.models import AnalysisReport, Paper

logger = logging.getLogger(__name__)

# 进程内调度标志（High 2d）：topic_dispatch 抓取/处理期间置 True，
# idle 检测读到即视为繁忙，避免 idle 与 topic_dispatch 抢同一批 unread 论文重复
# embed/skim。仅 worker 进程内生效（idle_processor 与 topic_dispatch 同在 worker 容器）。
_dispatching = False


def set_dispatching(value: bool) -> None:
    """设置 topic_dispatch 是否正在跑（供 worker main 调用）"""
    global _dispatching
    _dispatching = value


def is_dispatching() -> bool:
    """查询 topic_dispatch 是否正在跑"""
    return _dispatching


class IdleDetector:
    """
    系统空闲状态检测器

    检测指标：
    - CPU 使用率 < 30%
    - 内存使用率 < 70%
    - 无活跃用户请求（API 请求数 < 5/分钟）
    - 距离上次任务执行 > 10 分钟
    """

    def __init__(
        self,
        cpu_threshold: float = 30.0,
        memory_threshold: float = 70.0,
        request_threshold: int = 5,
        idle_interval: int = 600,
    ):
        self.cpu_threshold = cpu_threshold
        self.memory_threshold = memory_threshold
        self.request_threshold = request_threshold
        self.idle_interval = idle_interval  # 秒

        self._last_task_time = 0
        self._request_count = 0
        self._request_window = 60  # 1 分钟窗口
        self._request_timestamps = []

    def record_request(self):
        """记录一次 API 请求"""
        now = time.time()
        self._request_timestamps.append(now)

        # 清理过期记录
        cutoff = now - self._request_window
        self._request_timestamps = [ts for ts in self._request_timestamps if ts > cutoff]

    def _get_cpu_usage(self) -> float:
        """获取 CPU 使用率"""
        try:
            # 尝试使用 psutil
            import psutil

            return psutil.cpu_percent(interval=0.1)
        except ImportError:
            # 没有 psutil，返回保守估计值
            logger.debug("psutil 未安装，使用保守 CPU 估计")
            return 50.0

    def _get_memory_usage(self) -> float:
        """获取内存使用率"""
        try:
            import psutil

            return psutil.virtual_memory().percent
        except ImportError:
            logger.debug("psutil 未安装，使用保守内存估计")
            return 50.0

    def _get_recent_request_rate(self) -> int:
        """获取最近的请求速率（请求数/分钟）"""
        return len(self._request_timestamps)

    def is_idle(self) -> bool:
        """
        判断系统是否处于空闲状态

        Returns:
            bool: 是否空闲
        """
        # High 2d：topic_dispatch 正在抓取/处理时不算空闲，避免与 idle 抢同一批论文
        if is_dispatching():
            logger.debug("topic_dispatch 正在跑，不满足空闲条件")
            return False

        # 检查距离上次任务执行的时间
        if time.time() - self._last_task_time < self.idle_interval:
            return False

        # 检查 CPU
        cpu_usage = self._get_cpu_usage()
        if cpu_usage > self.cpu_threshold:
            logger.debug("CPU 使用率过高 (%.1f%%)，不满足空闲条件", cpu_usage)
            return False

        # 检查内存
        memory_usage = self._get_memory_usage()
        if memory_usage > self.memory_threshold:
            logger.debug("内存使用率过高 (%.1f%%)，不满足空闲条件", memory_usage)
            return False

        # 检查请求速率
        request_rate = self._get_recent_request_rate()
        if request_rate > self.request_threshold:
            logger.debug("请求速率过高 (%d/min)，不满足空闲条件", request_rate)
            return False

        logger.info(
            "✅ 系统空闲检测通过 (CPU=%.1f%%, Mem=%.1f%%, Req=%d/min)",
            cpu_usage,
            memory_usage,
            request_rate,
        )
        return True

    def mark_task_executed(self):
        """标记任务已执行，重置空闲计时器"""
        self._last_task_time = time.time()
        logger.debug("闲时任务执行完成，重置空闲计时器")


class IdleProcessor:
    """
    闲时自动处理器

    功能：
    - 定期检测系统空闲状态
    - 空闲时自动批量处理未读论文（只粗读 + 嵌入，不精读）
    - 遇到用户请求立即暂停
    - 可配置处理数量和并发度
    """

    def __init__(
        self,
        idle_detector: IdleDetector | None = None,
        batch_size: int = 5,
        check_interval: int = 60,
    ):
        self.detector = idle_detector or IdleDetector()
        self.batch_size = batch_size
        self.check_interval = check_interval  # 秒

        self._stop_event = Event()
        self._thread: Thread | None = None
        self._is_processing = False
        self._papers_processed = 0

    @staticmethod
    def _in_flight_paper_ids(capability: str) -> set[str]:
        """Go 权威任务表中该 capability 仍在排队/执行中的 paper_id 集合。

        闲时循环每轮都会重提同一批"卡住"的论文——若不查在途集合，同一篇论文
        会被反复提交（生产实证：deep_read 排队堆积到 63、embed/skim 大量重复
        LLM 调用）。表查询失败（如测试库无 core_tasks）返回空集不阻塞。
        """
        try:
            from sqlalchemy import text

            with session_scope() as session:
                rows = (
                    session.execute(
                        text(
                            "SELECT input_ref->>'paper_id' FROM core_tasks "
                            "WHERE capability = :cap AND status IN ('queued','leased','running')"
                        ),
                        {"cap": capability},
                    )
                    .scalars()
                    .all()
                )
                return {r for r in rows if r}
        except Exception:  # noqa: BLE001
            return set()

    def _get_unread_papers(self, limit: int = 10) -> list[tuple[str, str]]:
        """
        获取未读且未处理的论文

        Returns:
            list: [(paper_id, title), ...]
        """
        with session_scope() as session:
            papers = session.execute(
                select(Paper.id, Paper.title)
                .where(Paper.read_status == "unread")
                .outerjoin(AnalysisReport, Paper.id == AnalysisReport.paper_id)
                .where((AnalysisReport.summary_md.is_(None)) | (AnalysisReport.id.is_(None)))
                .order_by(Paper.created_at.asc())  # 优先处理旧的
                .limit(limit)
            ).all()
            return [(str(p.id), p.title) for p in papers]

    def _get_stuck_skimmed_papers(self, limit: int = 3) -> list[tuple[str, str]]:
        """获取已 skim 但卡住未精读的论文（Critical #6 补偿）

        之前只挑 unread 无 AnalysisReport 的论文走 embed+skim，但 skim 之后
        read_status 变 skimmed、deep_dive_md 仍为空——这些论文卡在 skimmed 永远
        不会被闲时补偿精读。这里挑出 skimmed 且 AnalysisReport 有 summary_md 但
        deep_dive_md 为空的论文，单独走 deep_dive 补偿，配额受限避免一次补偿太多。
        """
        with session_scope() as session:
            papers = session.execute(
                select(Paper.id, Paper.title)
                .where(Paper.read_status == "skimmed")
                .join(AnalysisReport, Paper.id == AnalysisReport.paper_id)
                .where(AnalysisReport.summary_md.is_not(None))
                .where(AnalysisReport.deep_dive_md.is_(None))
                # 来源无 PDF 的论文（arXiv 404 已持久标记）永久跳过——否则
                # deep_read 死信后 deep_dive_md 仍为空，每轮重提成重试风暴
                .where(Paper.metadata_json["pdf_unavailable"].as_boolean().is_not(True))
                .order_by(Paper.created_at.asc())  # 优先处理旧的
                .limit(limit)
            ).all()
            return [(str(p.id), p.title) for p in papers]

    def _submit_batch(self) -> int:
        """空闲时提交一批未读论文的 durable 批处理任务（C3 退出口：不直跑业务）。

        执行由 Executor 经 Go Core 调度（capability=batch_process_unread）。
        空闲 yield 语义退化为触发时间点检查——批次上限由 batch_size 约束，
        不会无限占用 LLM 配额。
        """
        from packages.application.commands.jobs import submit_job
        from packages.application.commands.task_registry import get_spec

        # 上一批 batch_process_unread 仍在途 → 本轮跳过（防重复提交）
        if self._in_flight_paper_ids("batch_process_unread"):
            logger.info("上一批闲时批处理仍在途，本轮跳过")
            return 0

        papers = self._get_unread_papers(limit=self.batch_size)
        if not papers:
            logger.info("没有需要处理的未读论文")
            return 0

        spec = get_spec("batch_process_unread")
        submitted = submit_job(
            kind="IdleBatchProcess",
            capability="batch_process_unread",
            title=f"🤖 闲时批处理 ({len(papers)} 篇)",
            input_ref={"max_papers": self.batch_size},
            resource_class=spec.resource_class,
            timeout_s=spec.timeout_s,
            max_attempts=spec.max_attempts,
            created_by="idle_processor",
        )
        self._papers_processed += len(papers)
        self.detector.mark_task_executed()
        logger.info(
            "🤖 闲时批处理已提交：%d 篇（task=%s）",
            len(papers),
            submitted["task_id"][:8],
        )
        return len(papers)

    def _compensate_stuck_skimmed(self) -> int:
        """补偿已 skim 但未精读的论文（Critical #6）。

        skim 完成后 read_status 变 skimmed，但 deep_dive_md 仍空的论文此前无人再
        触发精读，永久卡在 skimmed。闲时检测到即提交 deep_read durable 任务
        （配额受限，默认 2；deep_read_compensation 可调）。
        """
        from packages.application.commands.jobs import submit_job

        quota = getattr(get_settings(), "deep_read_compensation", 2)
        if quota <= 0:
            return 0

        stuck = self._get_stuck_skimmed_papers(limit=quota)
        # 排除已有在途 deep_read 任务的论文（否则每轮重提，重复 LLM 成本）
        inflight = self._in_flight_paper_ids("deep_read_paper")
        stuck = [(pid, title) for pid, title in stuck if pid not in inflight]
        if not stuck:
            return 0

        submitted = 0
        for paper_id, title in stuck:
            if not self.detector.is_idle():
                logger.warning("系统不再空闲，中止 skimmed 补偿")
                break
            submit_job(
                kind="IdleDeepRead",
                capability="deep_read_paper",
                title=f"🔧 闲时补偿精读：{title[:30]}",
                input_ref={"paper_id": str(paper_id)},
                resource_class="llm",
                timeout_s=1800,
                max_attempts=2,
                created_by="idle_processor",
            )
            submitted += 1
            time.sleep(0.5)
        logger.info("🔧 skimmed 补偿已提交：精读=%d/%d", submitted, len(stuck))
        return submitted

    def _run_loop(self):
        """主循环"""
        logger.info("🤖 闲时处理器启动")

        while not self._stop_event.is_set():
            try:
                # 检查是否空闲
                if self.detector.is_idle():
                    if not self._is_processing:
                        self._is_processing = True
                        self._submit_batch()
                        # Critical #6 补偿：独立于 skim 批次触发。此前补偿挂在
                        # 批处理末尾，但无 unread 论文时它提前 return 0，
                        # 补偿永远不跑。改为在 _run_loop 独立调用，无论有无
                        # unread 都尝试补偿 stuck 论文。
                        self._compensate_stuck_skimmed()
                        self._is_processing = False
                else:
                    if self._is_processing:
                        logger.info("暂停处理（系统繁忙）")
                        self._is_processing = False

                # 等待下一次检查
                self._stop_event.wait(self.check_interval)

            except Exception as e:
                logger.exception("闲时处理器异常：%s", e)
                self._is_processing = False
                time.sleep(10)

        logger.info("闲时处理器已停止")

    def start(self):
        """启动闲时处理器"""
        if self._thread and self._thread.is_alive():
            logger.warning("闲时处理器已在运行")
            return

        self._stop_event.clear()
        self._thread = Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("✅ 闲时处理器已启动")

    def stop(self):
        """停止闲时处理器"""
        logger.info("停止闲时处理器...")
        self._stop_event.set()

        if self._thread:
            self._thread.join(timeout=10)

        logger.info("闲时处理器已停止")

    def get_status(self) -> dict:
        """获取状态"""
        return {
            "running": self._thread is not None and self._thread.is_alive(),
            "is_processing": self._is_processing,
            "papers_processed": self._papers_processed,
            "batch_size": self.batch_size,
            "check_interval": self.check_interval,
        }


# 全局单例
_global_processor: IdleProcessor | None = None


def get_idle_processor() -> IdleProcessor:
    """获取全局闲时处理器实例"""
    global _global_processor

    if _global_processor is None:
        settings = get_settings()
        _global_processor = IdleProcessor(
            batch_size=getattr(settings, "idle_batch_size", 5),
            check_interval=getattr(settings, "idle_check_interval", 60),
        )

    return _global_processor


def start_idle_processor():
    """启动闲时处理器"""
    get_idle_processor().start()


def stop_idle_processor():
    """停止闲时处理器"""
    get_idle_processor().stop()


def record_api_request():
    """记录 API 请求（用于空闲检测）"""
    detector = getattr(_global_processor, "detector", None)
    if detector:
        detector.record_request()
