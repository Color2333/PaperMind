"""
每日报告服务 — 精读 / 生成简报 / 发送邮件三步解耦
@author Color2333

核心改造：
- 三个步骤可独立执行，也可组合为完整工作流
- build_html() 结果缓存（同一天内不重复计算）
- 新增 send_only() 方法，跳过精读直接发送
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime
from typing import Callable

from packages.config import get_settings
from packages.domain.exceptions import ConfigError, ServiceUnavailableError
from packages.domain.service_base import ServiceBase
from packages.storage.db import session_scope
from packages.storage.repositories import (
    DailyReportConfigRepository,
    EmailConfigRepository,
    PaperRepository,
)

logger = logging.getLogger(__name__)

# ---------- 简报 HTML 缓存 ----------

_brief_cache: dict[str, tuple[float, str]] = {}
_brief_cache_lock = threading.Lock()
_BRIEF_CACHE_TTL = get_settings().brief_cache_ttl


def _get_cached_html() -> str | None:
    """获取缓存的简报 HTML（同一天、5分钟内有效）"""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    with _brief_cache_lock:
        entry = _brief_cache.get(today)
        if entry and (time.monotonic() - entry[0]) < _BRIEF_CACHE_TTL:
            return entry[1]
    return None


def _set_cached_html(html: str) -> None:
    """缓存简报 HTML"""
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    with _brief_cache_lock:
        _brief_cache.clear()  # 只保留当天
        _brief_cache[today] = (time.monotonic(), html)


def invalidate_brief_cache() -> None:
    """手动清除简报缓存"""
    with _brief_cache_lock:
        _brief_cache.clear()


class AutoReadService(ServiceBase):
    """每日报告服务 — 支持独立步骤和完整工作流"""

    def get_config(self) -> dict:
        """获取每日报告配置"""
        with self.get_session() as session:
            config = DailyReportConfigRepository(session).get_config()
            return {
                "enabled": config.enabled,
                "auto_deep_read": config.auto_deep_read,
                "deep_read_limit": config.deep_read_limit,
                "send_email_report": config.send_email_report,
                "recipient_emails": config.recipient_emails.split(",") if config.recipient_emails else [],
                "report_time_utc": config.report_time_utc,
                "include_paper_details": config.include_paper_details,
                "include_graph_insights": config.include_graph_insights,
            }

    def update_config(self, **kwargs) -> dict:
        """更新每日报告配置"""
        with self.get_session() as session:
            config = DailyReportConfigRepository(session).update_config(**kwargs)
            return {
                "enabled": config.enabled,
                "auto_deep_read": config.auto_deep_read,
                "deep_read_limit": config.deep_read_limit,
                "send_email_report": config.send_email_report,
                "recipient_emails": config.recipient_emails.split(",") if config.recipient_emails else [],
                "report_time_utc": config.report_time_utc,
                "include_paper_details": config.include_paper_details,
                "include_graph_insights": config.include_graph_insights,
            }

    # ---------- 独立步骤 ----------

    def step_deep_read(
        self,
        progress_callback: Callable[[str, int, int], None] | None = None,
    ) -> dict:
        """
        步骤1: AI 推荐 + 自动精读

        Returns: {"recommended_count": int, "deep_read_count": int}
        """
        result = {"recommended_count": 0, "deep_read_count": 0}

        with self.get_session() as session:
            config = DailyReportConfigRepository(session).get_config()
            if not config.auto_deep_read:
                return result
            deep_read_limit = min(config.deep_read_limit, 5)

        if progress_callback:
            progress_callback("正在分析推荐论文...", 5, 100)

        try:
            from packages.ai.recommendation_service import RecommendationService
            recommendations = RecommendationService().recommend(top_k=deep_read_limit)
        except Exception as e:
            logger.error(f"推荐系统失败: {e}")
            return result

        # 筛选未精读的论文
        papers_to_read = []
        if recommendations:
            with self.get_session() as session:
                paper_repo = PaperRepository(session)
                for rec in recommendations:
                    paper = paper_repo.get_by_id(rec["id"])
                    if paper and paper.read_status.value != "deep_read":
                        papers_to_read.append({
                            "id": paper.id,
                            "title": paper.title,
                            "similarity": rec.get("similarity", 0),
                        })
            result["recommended_count"] = len(papers_to_read)

        # 执行精读
        if papers_to_read:
            from packages.ai.pipelines import PaperPipelines
            pipelines = PaperPipelines()
            for i, p in enumerate(papers_to_read, 1):
                try:
                    if progress_callback:
                        progress_callback(f"正在精读: {p['title'][:50]}", 5 + i * 15, 100)
                    pipelines.deep_dive(p["id"])
                    result["deep_read_count"] += 1
                except Exception as e:
                    logger.error(f"精读失败: {p['title']}, 错误: {e}")

        # 精读完成后清除简报缓存（数据变了）
        invalidate_brief_cache()
        return result

    def step_generate_html(
        self,
        progress_callback: Callable[[str, int, int], None] | None = None,
        use_cache: bool = True,
    ) -> str:
        """
        步骤2: 生成简报 HTML

        Args:
            use_cache: 是否使用缓存（默认 True，5分钟内不重复计算）

        Returns: HTML 字符串
        """
        if use_cache:
            cached = _get_cached_html()
            if cached:
                logger.info("使用缓存的简报 HTML")
                return cached

        if progress_callback:
            progress_callback("正在生成每日简报...", 60, 100)

        from packages.ai.brief_service import DailyBriefService
        html = DailyBriefService().build_html()
        _set_cached_html(html)
        return html

    def step_send_email(
        self,
        report_html: str,
        recipient_emails: list[str] | None = None,
        progress_callback: Callable[[str, int, int], None] | None = None,
    ) -> bool:
        """
        步骤3: 发送邮件

        Args:
            report_html: 简报 HTML 内容
            recipient_emails: 收件人列表（None 则从配置读取）

        Returns: 是否发送成功
        """
        # 收件人
        if not recipient_emails:
            with self.get_session() as session:
                config = DailyReportConfigRepository(session).get_config()
                emails_str = config.recipient_emails or ""
                recipient_emails = [e.strip() for e in emails_str.split(",") if e.strip()]

        if not recipient_emails:
            raise ConfigError("未配置收件人邮箱")

        # 获取激活的邮箱配置
        with self.get_session() as session:
            email_config = EmailConfigRepository(session).get_active()

        if not email_config:
            raise ConfigError("未配置激活的邮箱，请先在邮箱设置中添加并激活一个邮箱配置")

        if progress_callback:
            progress_callback("正在发送邮件报告...", 90, 100)

        from packages.integrations.email_service import EmailService
        email_service = EmailService(email_config)
        report_date = datetime.now().strftime("%Y-%m-%d")

        success = email_service.send_daily_report(
            to_emails=recipient_emails,
            report_html=report_html,
            report_date=report_date,
        )

        if not success:
            raise ServiceUnavailableError("邮件发送失败，请检查 SMTP 配置")

        return True

    # ---------- 组合工作流 ----------

    async def run_daily_workflow(
        self,
        progress_callback: Callable[[str, int, int], None] | None = None,
    ) -> dict:
        """
        完整工作流: 精读 → 生成简报 → 发送邮件

        向后兼容原有接口
        """
        result = {
            "success": False,
            "recommended_count": 0,
            "deep_read_count": 0,
            "brief_generated": False,
            "email_sent": False,
            "error": None,
        }

        try:
            # 检查是否启用
            with self.get_session() as session:
                config = DailyReportConfigRepository(session).get_config()
                if not config.enabled:
                    logger.info("每日报告功能未启用")
                    return result
                send_email_report = config.send_email_report

            # 步骤1: 精读
            deep_result = self.step_deep_read(progress_callback)
            result["recommended_count"] = deep_result["recommended_count"]
            result["deep_read_count"] = deep_result["deep_read_count"]

            # 步骤2: 生成简报（精读完后不用缓存，确保包含最新数据）
            report_html = self.step_generate_html(progress_callback, use_cache=False)
            result["brief_generated"] = True

            # 步骤3: 发送邮件
            if send_email_report:
                try:
                    self.step_send_email(report_html, progress_callback=progress_callback)
                    result["email_sent"] = True
                except (ConfigError, ServiceUnavailableError) as e:
                    result["error"] = str(e)
                    # 邮件失败不影响整体成功
                    logger.warning(f"邮件发送失败: {e}")

            result["success"] = True
            return result

        except Exception as e:
            logger.error(f"每日工作流执行失败: {e}", exc_info=True)
            result["error"] = str(e)
            return result

    def send_only(
        self,
        recipient_emails: list[str] | None = None,
        progress_callback: Callable[[str, int, int], None] | None = None,
    ) -> dict:
        """
        快速发送模式 — 跳过精读，直接生成简报并发邮件

        优先使用缓存的简报 HTML，大幅加速测试和重发场景
        """
        result = {
            "success": False,
            "brief_generated": False,
            "email_sent": False,
            "used_cache": False,
            "error": None,
        }

        try:
            # 生成简报（优先缓存）
            if progress_callback:
                progress_callback("正在准备简报...", 10, 100)

            cached = _get_cached_html()
            if cached:
                report_html = cached
                result["used_cache"] = True
            else:
                report_html = self.step_generate_html(progress_callback, use_cache=True)
            result["brief_generated"] = True

            # 发送邮件
            self.step_send_email(report_html, recipient_emails, progress_callback)
            result["email_sent"] = True
            result["success"] = True

            if progress_callback:
                progress_callback("邮件发送成功！", 100, 100)

            return result

        except (ConfigError, ServiceUnavailableError) as e:
            result["error"] = str(e)
            return result
        except Exception as e:
            logger.error(f"快速发送失败: {e}", exc_info=True)
            result["error"] = str(e)
            return result


async def trigger_auto_read(
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> dict:
    """触发自动精读工作流的便捷函数"""
    service = AutoReadService()
    return await service.run_daily_workflow(progress_callback)
