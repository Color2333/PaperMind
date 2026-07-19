"""LangGraph ReAct graph：复刻 StreamingAgentLoop 的 run + confirm 暂停/恢复。

关键映射：
- agent 节点：调 PaperMindChatModel（已 bind_tools 所有 27 工具）
- should_continue：tool_calls 非空 → tools 节点，否则 END
- tools 节点：遍历 tool_calls；auto 直接执行，confirm 调 interrupt()
- interrupt resume 值形状：{"confirmed": bool, "action_id": str}
- interrupt value 形状：{"tool": str, "args": dict, "tool_call_id": str, "action_id": str}

@author Color2333
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.config import get_stream_writer
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from packages.langgraph_agent.chat_model import PaperMindChatModel
from packages.langgraph_agent.state import AgentState
from packages.langgraph_agent.tools_adapter import (
    CONFIRM_NAMES,
    describe_action,
    reject_tool_msg,
    run_tool,
)

logger = logging.getLogger(__name__)

# 默认递归上限（替代老 loop 的 max_rounds=12；agent+tools 一轮算 2 步）
DEFAULT_RECURSION_LIMIT = 24


def _make_action_id(thread_id: str, tool_call_id: str) -> str:
    """从 thread_id + tool_call_id 确定性派生 action_id。

    必须确定性：LangGraph 恢复时会重新执行 call_tools 节点，再次走 interrupt()
    分支（此时 interrupt 立即返回 resume 值不暂停），若 action_id 随机则与首次
    interrupt 时不一致，导致路由层 pending action 反查失败。
    """
    import hashlib

    raw = f"{thread_id}:{tool_call_id}"
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return f"act_{digest[:8]}_{digest[8:16]}"


def _build_agent_node(model: PaperMindChatModel):
    def call_model(state: AgentState) -> dict:
        messages = state["messages"]
        # PaperMindChatModel 已 bind_tools；直接 invoke
        ai_msg = model.invoke(messages)
        return {"messages": [ai_msg]}

    return call_model


def _should_continue(state: AgentState) -> str:
    last = state["messages"][-1]
    # tool_calls 优先从顶层 .tool_calls（langchain 1.x），回退 additional_kwargs（旧版/流式聚合）
    tool_calls = getattr(last, "tool_calls", None) or (last.additional_kwargs or {}).get(
        "tool_calls"
    )
    return "tools" if tool_calls else END


def _build_tools_node(thread_id: str, model: PaperMindChatModel):
    """工具节点：auto 直接执行，confirm 调 interrupt 暂停。"""

    def call_tools(state: AgentState) -> dict:
        ai_msg = state["messages"][-1]
        # tool_calls 优先从 .tool_calls（langchain 新协议）取，回退 additional_kwargs
        tool_calls = getattr(ai_msg, "tool_calls", None)
        if not tool_calls:
            tool_calls = (ai_msg.additional_kwargs or {}).get("tool_calls", [])
        writer = None
        try:
            writer = get_stream_writer()
        except Exception:
            # 非图执行上下文（如单测直接调），writer 不可用
            writer = None

        results: list = []
        for tc in tool_calls:
            name = tc["name"]
            args = tc.get("args") or {}
            tc_id = tc.get("id") or ""
            tc_dict = {"name": name, "args": args, "id": tc_id}

            if name in CONFIRM_NAMES:
                action_id = _make_action_id(thread_id, tc_id)
                desc = describe_action(name, args)
                # interrupt：value 携带恢复所需信息；前端据此渲染确认卡
                resume_value = interrupt(
                    {
                        "tool": name,
                        "args": args,
                        "tool_call_id": tc_id,
                        "action_id": action_id,
                        "description": desc,
                    }
                )
                # resume_value 来自 /agent/v2/confirm 或 /reject 的 Command(resume={"confirmed": bool, ...})
                confirmed = bool(resume_value.get("confirmed"))
                if confirmed:
                    # 执行 + 发 action_result
                    tool_msg, result_dict = run_tool(tc_dict, writer)
                    if writer:
                        writer(
                            {
                                "type": "action_result",
                                "data": {
                                    "id": action_id,
                                    "success": result_dict["success"],
                                    "summary": result_dict["summary"],
                                    "data": result_dict["data"],
                                },
                            }
                        )
                    results.append(tool_msg)
                else:
                    # 拒绝：注入拒绝 tool 消息 + 发 action_result(success=False)
                    reject_msg = reject_tool_msg(tc_dict)
                    if writer:
                        writer(
                            {
                                "type": "action_result",
                                "data": {
                                    "id": action_id,
                                    "success": False,
                                    "summary": "用户已取消该操作",
                                    "data": {},
                                },
                            }
                        )
                    results.append(reject_msg)
            else:
                # auto 工具：直接执行（run_tool 已发 tool_start/tool_progress/tool_result）
                tool_msg, _ = run_tool(tc_dict, writer)
                results.append(tool_msg)
        return {"messages": results}

    return call_tools


def build_graph(
    checkpointer: Any, model: PaperMindChatModel | None = None, thread_id: str = "default"
):
    """构建并编译 ReAct graph。

    thread_id：用于派生 action_id（多 confirm 时唯一）。每个请求应传 conversation_id。
    """
    if model is None:
        from packages.ai.tools import TOOL_REGISTRY

        model = PaperMindChatModel()
        model = model.bind_tools(TOOL_REGISTRY)
        # 注入 usage 回调
        from packages.ai.agent_service import _record_agent_usage

        object.__setattr__(model, "on_usage", _record_agent_usage)

    g = StateGraph(AgentState)
    g.add_node("agent", _build_agent_node(model))
    g.add_node("tools", _build_tools_node(thread_id, model))
    g.set_entry_point("agent")
    g.add_conditional_edges("agent", _should_continue, {"tools": "tools", END: END})
    g.add_edge("tools", "agent")
    return g.compile(checkpointer=checkpointer)


__all__ = ["build_graph", "DEFAULT_RECURSION_LIMIT"]
