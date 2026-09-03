"""简报生成命令（B6，设计② StartDailyBrief 的同步语义）

build → 落盘 → 可选发邮件 → 写 generated_contents（带 3 次重试）。
邮件发送不可安全重放——Stage C 中标记 manual_recovery。
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime

from packages.application.commands.jobs import submit_tracked_compat
from packages.application.commands.task_registry import get_spec

logger = logging.getLogger(__name__)


def publish_daily_brief(*, recipient: str = "", limit: int = 30) -> dict:
    """生成并保存每日简报，返回 {saved_path, email_sent, html, title}"""
    from packages.ai.brief_service import DailyBriefService
    from packages.integrations.notifier import NotificationService
    from packages.storage.db import session_scope
    from packages.storage.repositories import GeneratedContentRepository

    html_content = DailyBriefService().build_html(limit=limit)
    ts_label = datetime.now(UTC).strftime("%Y-%m-%d")
    ts_file = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")

    notifier = NotificationService()
    saved_path = notifier.save_brief_html(f"daily_brief_{ts_file}.html", html_content)

    email_sent = False
    clean_recipient = recipient.strip() if recipient else ""
    if clean_recipient:
        email_sent = notifier.send_email_html(
            clean_recipient, "PaperMind Daily Brief", html_content
        )

    db_saved = False
    for attempt in range(3):
        try:
            with session_scope() as session:
                GeneratedContentRepository(session).create(
                    content_type="daily_brief",
                    title=f"Daily Brief: {ts_label}",
                    markdown=html_content,
                )
            db_saved = True
            break
        except Exception as exc:
            logger.warning("简报保存到数据库失败 (attempt %d): %s", attempt + 1, exc)
            time.sleep(1)

    if not db_saved:
        logger.error("简报保存到数据库最终失败，但文件已保存: %s", saved_path)

    return {
        "saved_path": saved_path,
        "email_sent": email_sent,
        "html": html_content,
        "title": f"研究简报: {ts_label}",
    }


def start_daily_brief_task(*, recipient: str | None = None) -> dict:
    """提交每日简报后台任务（recipient 缺省时读 DB 配置；tracker 过渡）"""
    from packages.storage.db import session_scope
    from packages.storage.repositories import DailyReportConfigRepository

    if not recipient:
        with session_scope() as session:
            config = DailyReportConfigRepository(session).get_config()
            if config.send_email_report and config.recipient_emails:
                recipient = config.recipient_emails.split(",")[0]

    def _fn(progress_callback=None):
        if progress_callback:
            progress_callback("正在生成每日简报...", 20, 100)
        # HTTP 语义 = DailyBriefService.publish（返回含 content_id，与原路由一致）
        from packages.ai.brief_service import DailyBriefService

        result = DailyBriefService().publish(recipient=recipient)
        if progress_callback:
            progress_callback("简报生成完成", 95, 100)
        return result

    spec = get_spec("build_daily_brief")
    task_id = submit_tracked_compat(
        kind="StartDailyBrief",
        capability="build_daily_brief",
        task_type="daily_brief",
        title="📰 生成每日简报",
        fn=_fn,
        total=100,
        category="generation",
        timeout_s=spec.timeout_s,
        max_attempts=spec.max_attempts,
    )
    return {
        "task_id": task_id,
        "status": "started",
        "message": "日报生成已启动，预计需要 1-3 分钟...",
    }
