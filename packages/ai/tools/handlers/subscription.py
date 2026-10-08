"""主题订阅列表与管理（业务在 application/queries/topics.py）"""

from __future__ import annotations

import logging

from packages.ai.tools.types import ToolResult
from packages.application.commands.topics import update_subscription
from packages.application.queries.topics import list_topics
from packages.domain.exceptions import NotFoundError
from packages.storage.db import session_scope

logger = logging.getLogger(__name__)


def _list_topics() -> ToolResult:
    try:
        with session_scope() as session:
            items = list_topics(session, enabled_only=False)
        enabled = sum(1 for t in items if t["enabled"])
        names = ", ".join(t["name"] for t in items[:5])
        suffix = "..." if len(items) > 5 else ""
        return ToolResult(
            success=True,
            data={"topics": items, "count": len(items)},
            summary=f"共 {len(items)} 个主题（{enabled} 个已订阅）: {names}{suffix}",
        )
    except Exception as exc:
        logger.exception("list_topics failed: %s", exc)
        return ToolResult(success=False, summary=f"列出主题失败: {exc!s}")


def _manage_subscription(
    topic_name: str,
    enabled: bool,
    schedule_frequency: str | None = None,
    schedule_time_beijing: int | None = None,
) -> ToolResult:
    """管理主题订阅：启用/禁用、设置频率和时间"""
    freq_map = {
        "daily": "每天",
        "twice_daily": "每天两次",
        "weekdays": "工作日",
        "weekly": "每周",
    }
    try:
        with session_scope() as session:
            data = update_subscription(
                session,
                topic_name=topic_name,
                enabled=enabled,
                schedule_frequency=schedule_frequency,
                schedule_time_beijing=schedule_time_beijing,
            )
    except NotFoundError:
        return ToolResult(success=False, summary=f"主题「{topic_name}」不存在")
    except Exception as exc:
        logger.exception("manage_subscription failed: %s", exc)
        return ToolResult(success=False, summary=f"管理订阅失败: {exc!s}")

    freq_label = freq_map.get(
        data["schedule_frequency_effective"], data["schedule_frequency_effective"]
    )
    bj_hour = data["bj_hour_effective"]
    action = "启用定时搜集" if enabled else "关闭定时搜集"
    schedule_info = f"（{freq_label} · 北京时间 {bj_hour:02d}:00）"

    return ToolResult(
        success=True,
        data=data,
        summary=f"已{action}：{topic_name} {schedule_info}",
    )
