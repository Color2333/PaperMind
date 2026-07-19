"""LangGraph agent 入口：stream_chat_v2 / confirm_v2 / reject_v2。

复用现有 _build_messages（system prompt + 用户画像）+ _db_messages_to_openai（后端拼历史），
然后把 OpenAI dict 转成 LangChain BaseMessage 喂给 graph。

@author Color2333
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.types import Command

from packages.langgraph_agent.checkpointer import get_checkpointer
from packages.langgraph_agent.graph import DEFAULT_RECURSION_LIMIT, build_graph
from packages.langgraph_agent.sse_adapter import stream_to_sse

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)


def _openai_dicts_to_langchain(dicts: list[dict]) -> list[Any]:
    """OpenAI dict → LangChain BaseMessage。与 chat_model._pm_messages_to_openai 互逆。"""
    out: list[Any] = []
    for m in dicts:
        role = m.get("role", "user")
        if role == "system":
            out.append(SystemMessage(content=m.get("content", "")))
        elif role == "user":
            out.append(HumanMessage(content=m.get("content", "")))
        elif role == "assistant":
            tcs = m.get("tool_calls") or []
            tool_calls = [
                {
                    "name": tc["function"]["name"],
                    "args": tc["function"]["arguments"],
                    "id": tc["id"],
                    "type": "tool_call",
                }
                for tc in tcs
            ]
            # args 可能是 str 或 dict；AIMessage 期望 args 是 dict 或 JSON str
            normalized_tc = []
            for tc in tool_calls:
                args = tc["args"]
                if isinstance(args, str):
                    import json

                    try:
                        args = json.loads(args) if args else {}
                    except (json.JSONDecodeError, TypeError):
                        args = {}
                normalized_tc.append(
                    {"name": tc["name"], "args": args, "id": tc["id"], "type": "tool_call"}
                )
            out.append(
                AIMessage(
                    content=m.get("content") or "",
                    tool_calls=normalized_tc if normalized_tc else [],
                )
            )
        elif role == "tool":
            out.append(
                ToolMessage(
                    content=m.get("content", ""),
                    tool_call_id=m.get("tool_call_id", ""),
                )
            )
    return out


def _build_langchain_messages(openai_dicts: list[dict]) -> list[Any]:
    """复用 agent_service._build_messages（system prompt + 用户画像）后转 LangChain。"""
    from packages.ai.agent_service import _build_messages

    with_profile = _build_messages(openai_dicts)
    return _openai_dicts_to_langchain(with_profile)


def stream_chat_v2(
    openai_msgs: list[dict],
    conversation_id: str,
    confirmed_action_id: str | None = None,
) -> tuple[Iterator[str], str]:
    """LangGraph 版 agent 对话入口。

    openai_msgs: 路由层已拼好 DB 历史 + 本次新消息（OpenAI dict 格式）。
    conversation_id: 即 thread_id（复用 AgentConversation.id）。
    confirmed_action_id: 若非空，表示从 confirm 恢复，用 Command(resume=...)。
    返回 (SSE 事件流, conversation_id)。
    """
    cp = get_checkpointer()
    config: dict = {
        "configurable": {"thread_id": conversation_id},
        "recursion_limit": DEFAULT_RECURSION_LIMIT,
    }

    if confirmed_action_id:
        # 从 confirm 恢复：Command(resume={"confirmed": True, "action_id": ...})
        input_data: Any = Command(resume={"confirmed": True, "action_id": confirmed_action_id})
    else:
        langchain_msgs = _build_langchain_messages(openai_msgs)
        input_data = {"messages": langchain_msgs}

    graph = build_graph(cp, thread_id=conversation_id)
    sse_iter = stream_to_sse(graph, input_data, config)
    return sse_iter, conversation_id


def confirm_v2(action_id: str, conversation_id: str | None) -> tuple[Iterator[str], str | None]:
    """确认挂起的操作：Command(resume={"confirmed": True})。"""
    if not conversation_id:
        logger.warning("confirm_v2: 无 conversation_id，无法恢复（checkpoint 缺失）")
        return _err_iter("该操作已过期（无法定位会话）。请重新描述您的需求。"), None

    cp = get_checkpointer()
    config: dict = {
        "configurable": {"thread_id": conversation_id},
        "recursion_limit": DEFAULT_RECURSION_LIMIT,
    }
    graph = build_graph(cp, thread_id=conversation_id)
    sse_iter = stream_to_sse(
        graph, Command(resume={"confirmed": True, "action_id": action_id}), config
    )
    return sse_iter, conversation_id


def reject_v2(action_id: str, conversation_id: str | None) -> tuple[Iterator[str], str | None]:
    """拒绝挂起的操作：Command(resume={"confirmed": False})。LLM 会收到拒绝 tool 消息并给替代方案。"""
    if not conversation_id:
        logger.warning("reject_v2: 无 conversation_id，无法恢复")
        return _err_iter("该操作已过期（无法定位会话）。请重新描述您的需求。"), None

    cp = get_checkpointer()
    config: dict = {
        "configurable": {"thread_id": conversation_id},
        "recursion_limit": DEFAULT_RECURSION_LIMIT,
    }
    graph = build_graph(cp, thread_id=conversation_id)
    sse_iter = stream_to_sse(
        graph, Command(resume={"confirmed": False, "action_id": action_id}), config
    )
    return sse_iter, conversation_id


def _err_iter(msg: str) -> Iterator[str]:
    """错误流：error + done（与老 agent_service 的 _err_iter 同形）。"""
    from packages.agent_core.sse import make_sse

    yield make_sse("error", {"message": msg})
    yield make_sse("done", {})


__all__ = ["stream_chat_v2", "confirm_v2", "reject_v2"]
