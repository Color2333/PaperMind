"""系统状态查询（业务在 application/queries/system.py）"""

from __future__ import annotations

import logging

from packages.ai.tools.types import ToolResult
from packages.application.queries.system import get_system_status

logger = logging.getLogger(__name__)


def _get_system_status() -> ToolResult:
    try:
        data = get_system_status()
    except Exception as exc:
        logger.exception("get_system_status failed: %s", exc)
        return ToolResult(success=False, summary=f"获取系统状态失败: {exc!s}")
    db_ok = data["db_connected"]
    return ToolResult(
        success=True,
        data=data,
        summary=(
            f"论文 {data['paper_count']} 篇（{data['embedded_count']} 已向量化），"
            f"主题 {data['topic_count']} 个" + ("" if db_ok else " ⚠️数据库异常")
        ),
    )
