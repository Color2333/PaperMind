"""学术写作助手。"""

from __future__ import annotations

import logging

from packages.ai.tools.types import ToolResult

logger = logging.getLogger(__name__)


def _writing_assist(action: str, text: str) -> ToolResult:
    """学术写作助手"""
    from packages.ai.writing_service import TEMPLATE_MAP, WritingAction, WritingService

    try:
        wa = WritingAction(action)
    except ValueError:
        return ToolResult(success=False, summary=f"未知的写作操作: {action}")

    template = TEMPLATE_MAP.get(wa)
    label = template.label if template else action

    try:
        result = WritingService().process(action, text)
    except Exception as exc:
        logger.exception("Writing assist failed: %s", exc)
        return ToolResult(success=False, summary=f"写作助手执行失败: {exc!s}")

    content = result.get("content", "")
    return ToolResult(
        success=True,
        data={
            "action": action,
            "label": label,
            "content": content,
            "input_tokens": result.get("input_tokens"),
            "output_tokens": result.get("output_tokens"),
        },
        summary=f"「{label}」处理完成:\n\n{content[:2000]}",
    )
