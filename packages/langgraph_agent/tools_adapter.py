"""工具适配层：复用现有 TOOL_REGISTRY + execute_tool_stream。

设计：不重建 langchain StructuredTool，而是直接把 ToolDef 列表喂给
PaperMindChatModel.bind_tools（已支持 ToolDef → OpenAI spec）。
这里只提供：
- CONFIRM_NAMES：confirm 工具集合（graph 的 call_tools 节点用它判断走 interrupt）
- run_tool(tc)：执行一个 tool_call，yield SSE 事件 + 返回 ToolMessage
- describe_action：复用现有 ConfirmationMixin 的描述生成

@author Color2333
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import ToolMessage

from packages.ai.tools import TOOL_REGISTRY, ToolProgress, ToolResult, execute_tool_stream

# confirm 工具集合：从 TOOL_REGISTRY 派生（与老 loop.py:244 同源）
CONFIRM_NAMES: set[str] = {t.name for t in TOOL_REGISTRY if getattr(t, "requires_confirm", False)}


# 复用老 ConfirmationMixin 的 describe_action 逻辑（避免重复实现）
def describe_action(tool_name: str, args: dict) -> str:
    """生成人工确认卡片的中文描述。复用 packages.agent_core.loop.ConfirmationMixin。"""
    try:
        from packages.agent_core.loop import ConfirmationMixin
        from packages.storage.db import session_scope

        mixin = ConfirmationMixin(
            confirm_tools=CONFIRM_NAMES,
            pending_repo_class=None,
            session_scope=session_scope,
        )
        return mixin.describe_action(tool_name, args)
    except Exception:
        return f"执行 {tool_name}"


def run_tool(tool_call: dict, writer: Any = None) -> tuple[ToolMessage, dict]:
    """执行一个 tool_call，返回 (ToolMessage, result_dict)。

    writer: LangGraph get_stream_writer() 返回的回调，用于发 tool_start/tool_progress/tool_result。
    若 writer 为 None（如单元测试），事件被丢弃，只返回结果。

    tool_call 形状：{"name": str, "args": dict, "id": str}
    """
    name = tool_call["name"]
    args = tool_call.get("args") or {}
    tool_call_id = tool_call.get("id") or ""

    # tool_start
    if writer:
        writer({"type": "tool_start", "data": {"id": tool_call_id, "name": name, "args": args}})

    result = ToolResult(success=False, summary="无结果")
    for item in execute_tool_stream(name, args):
        if isinstance(item, ToolProgress):
            if writer:
                writer(
                    {
                        "type": "tool_progress",
                        "data": {
                            "id": tool_call_id,
                            "message": item.message,
                            "current": item.current,
                            "total": item.total,
                        },
                    }
                )
        elif isinstance(item, ToolResult):
            result = item
        else:
            # duck-typed（agent_tools.ToolResult）
            result = ToolResult(
                success=getattr(item, "success", False),
                data=getattr(item, "data", {}) or {},
                summary=getattr(item, "summary", ""),
            )

    # tool_result（auto 工具；confirm 工具用 action_result，由 graph 节点发）
    if writer:
        writer(
            {
                "type": "tool_result",
                "data": {
                    "id": tool_call_id,
                    "name": name,
                    "success": result.success,
                    "summary": result.summary,
                    "data": result.data,
                },
            }
        )

    # 构造回传给 LLM 的 tool 消息（JSON 字符串内容，与老 loop.py:428-434 同形）
    content = json.dumps(
        {"success": result.success, "summary": result.summary, "data": result.data},
        ensure_ascii=False,
    )
    tool_msg = ToolMessage(content=content, tool_call_id=tool_call_id)
    return tool_msg, {
        "name": name,
        "success": result.success,
        "summary": result.summary,
        "data": result.data,
    }


def reject_tool_msg(tool_call: dict) -> ToolMessage:
    """拒绝执行：注入"用户已取消"tool 消息，与老 loop.py:566-575 同形。"""
    content = json.dumps(
        {
            "success": False,
            "summary": "用户拒绝了此操作，请提供替代方案",
            "data": {},
        },
        ensure_ascii=False,
    )
    return ToolMessage(content=content, tool_call_id=tool_call.get("id") or "")


__all__ = [
    "CONFIRM_NAMES",
    "describe_action",
    "run_tool",
    "reject_tool_msg",
]
