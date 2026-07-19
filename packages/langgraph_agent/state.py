"""LangGraph Agent 状态定义。

@author Color2333
"""

from __future__ import annotations

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """ReAct agent 状态：消息列表（LangGraph add_messages reducer 自动累加）。"""

    messages: Annotated[list, add_messages]


__all__ = ["AgentState"]
