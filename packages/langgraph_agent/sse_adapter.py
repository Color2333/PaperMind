"""SSE 适配层：把 LangGraph 多 stream_mode 转成现有 9 种 SSE 事件。

消费 stream_mode=["messages", "custom", "updates"]：
- messages: AIMessageChunk.content → text_delta
- custom:   工具节点 get_stream_writer() 发的事件 → 原样转发
- updates:  __interrupt__ → action_confirm；其余忽略

conversation_init 由路由层发（与老 agent.py:180 一致），不在此处。
done 在图结束后发。

@author Color2333
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessageChunk
from langgraph.types import Command

from packages.agent_core.sse import make_sse

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)


def _describe_for_confirm(iv: dict) -> str:
    """从 interrupt value 取 description；若上游已生成则直接用，否则现场生成。"""
    if iv.get("description"):
        return iv["description"]
    try:
        from packages.langgraph_agent.tools_adapter import describe_action

        return describe_action(iv["tool"], iv.get("args") or {})
    except Exception:
        return f"执行 {iv.get('tool', '未知操作')}"


def stream_to_sse(graph: Any, input: Any, config: dict) -> Iterator[str]:
    """运行 LangGraph 并把流式输出转成现有 SSE wire format。

    graph: 已编译的 CompiledStateGraph
    input: 初始 state 或 Command(resume=...)
    config: {"configurable": {"thread_id": ...}}
    """
    try:
        from langgraph.errors import GraphRecursionError
    except ImportError:
        GraphRecursionError = Exception  # type: ignore[assignment, misc]

    try:
        stream = graph.stream(
            input,
            config,
            stream_mode=["messages", "custom", "updates"],
        )
        for mode, chunk in stream:
            if mode == "messages":
                # chunk = (message, metadata)
                if isinstance(chunk, tuple) and len(chunk) >= 1:
                    msg = chunk[0]
                    if isinstance(msg, AIMessageChunk) and msg.content:
                        yield make_sse("text_delta", {"content": msg.content})
            elif mode == "custom":
                # 工具节点用 get_stream_writer() 发的 dict：{"type": ..., "data": ...}
                if isinstance(chunk, dict) and "type" in chunk and "data" in chunk:
                    yield make_sse(chunk["type"], chunk["data"])
            elif mode == "updates":  # noqa: SIM102  多分支 dispatch，非嵌套 if
                # 检测 __interrupt__（合并条件，避免 SIM 报嵌套 if）
                if (
                    isinstance(chunk, dict)
                    and "__interrupt__" in chunk
                    and chunk["__interrupt__"]
                    and isinstance(chunk["__interrupt__"][0].value, dict)
                    and "tool" in chunk["__interrupt__"][0].value
                ):
                    iv = chunk["__interrupt__"][0].value
                    action_id = (
                        iv.get("action_id") or f"act_{iv.get('tool_call_id', 'unknown')[-12:]}"
                    )
                    yield make_sse(
                        "action_confirm",
                        {
                            "id": action_id,
                            "tool": iv["tool"],
                            "args": iv.get("args") or {},
                            "description": _describe_for_confirm(iv),
                        },
                    )
            # 其余 mode（如 "values"）忽略
    except GraphRecursionError:
        # max_rounds 耗尽（recursion_limit），与老 loop ⑩ 同形提示
        yield make_sse(
            "text_delta", {"content": "\n\n[已达到本轮最大对话轮次，如有需要请继续提问]"}
        )
    except Exception as exc:
        logger.exception("LangGraph stream 失败: %s", exc)
        yield make_sse("error", {"message": f"Agent 执行失败: {exc!s}"})

    yield make_sse("done", {})


__all__ = ["stream_to_sse", "Command"]
