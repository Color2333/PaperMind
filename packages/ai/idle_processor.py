"""
闲时自动处理器 - 检测系统空闲状态，自动批量处理未读论文
@author Color2333
"""

from __future__ import annotations

import logging
import time
from threading import Event, Thread

from sqlalchemy import select

from packages.ai.pipelines import PaperPipelines
from packages.ai.rate_limiter import acquire_api, get_rate_limiter
from packages.config import get_settings
from packages.storage.db import session_scope
from packages.storage.models import AnalysisReport, Paper

logger = logging.getLogger(__name__)


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

    def _process_batch(self) -> int:
        """
        处理一批论文（带任务追踪）

        Returns:
            int: 处理的论文数量
        """
        from packages.domain.task_tracker import global_tracker

        papers = self._get_unread_papers(limit=self.batch_size)

        if not papers:
            logger.info("没有需要处理的未读论文")
            return 0

        # 启动任务追踪
        task_id = f"idle_skim_{int(time.time())}"
        global_tracker.start(
            task_id=task_id,
            task_type="idle_skim",
            title=f"🤖 闲时粗读 ({len(papers)} 篇)",
            total=len(papers),
        )

        logger.info("📝 闲时处理开始：%d 篇论文 (并发度=3)", len(papers))

        processed = 0
        failed = 0
        pipelines = PaperPipelines()
        limiter = get_rate_limiter()

        try:
            for i, (paper_id, title) in enumerate(papers):
                # 检查是否应该暂停
                if not self.detector.is_idle():
                    logger.warning("系统不再空闲，暂停处理")
                    global_tracker.update(
                        task_id=task_id,
                        current=processed,
                        message="系统繁忙，暂停处理",
                    )
                    break

                # 更新进度
                global_tracker.update(
                    task_id=task_id,
                    current=i + 1,
                    message=f"处理：{title[:50]}...",
                )

                # 检查并发许可
                if not limiter.start_task():
                    logger.debug("并发数已达上限，等待...")
                    time.sleep(2)
                    continue

                try:
                    logger.info("处理：%s", title[:50])

                    # 获取 API 许可
                    if not acquire_api("embedding", timeout=30.0):
                        logger.warning("Embedding API 限流，跳过")
                        failed += 1
                        continue

                    # 嵌入
                    try:
                        pipelines.embed_paper(str(paper_id))
                        logger.info("✅ 嵌入完成：%s", title[:40])
                    except Exception as e:
                        logger.warning("嵌入失败：%s - %s", title[:40], e)
                        failed += 1
                        continue

                    # 获取 API 许可
                    if not acquire_api("llm", timeout=30.0):
                        logger.warning("LLM API 限流，跳过粗读")
                        continue

                    # 粗读
                    try:
                        result = pipelines.skim(str(paper_id))
                        score = result.relevance_score if result else None
                        logger.info("✅ 粗读完成：%s (分数=%.2f)", title[:40], score or 0)
                    except Exception as e:
                        logger.warning("粗读失败：%s - %s", title[:40], e)
                        failed += 1
                        continue

                    processed += 1

                    # 短暂休息，避免过于频繁
                    time.sleep(1)

                finally:
                    limiter.end_task()

            global_tracker.finish(task_id, success=True)
            logger.info("📊 闲时处理完成：成功=%d, 失败=%d", processed, failed)

        except Exception as exc:
            global_tracker.finish(task_id, success=False, error=str(exc)[:200])
            logger.error("❌ 闲时处理失败：%s", exc)

        self._papers_processed += processed
        self.detector.mark_task_executed()

        return processed

    def _run_loop(self):
        """主循环"""
        logger.info("🤖 闲时处理器启动")

        while not self._stop_event.is_set():
            try:
                # 检查是否空闲
                if self.detector.is_idle():
                    if not self._is_processing:
                        self._is_processing = True
                        self._process_batch()
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
