"""LangGraph ReAct graph：复刻 StreamingAgentLoop 的 run + confirm 暂停/恢复。

关键映射：
- agent 节点：调 PaperMindChatModel（已 bind_tools 所有 27 工具）
- should_continue：tool_calls 非空 → tools 节点，否则 END
- tools 节点：遍历 tool_calls；auto 直接执行，confirm 调 interrupt()
- interrupt resume 值形状：{"confirmed": bool, "action_id": str}
- interrupt value 形状：{"tool": str, "args": dict, "tool_call_id": str, "action_id": str}

性能优化：编译后的 graph 缓存复用，不每请求重建。thread_id 在运行时
从 get_config() 读（config["configurable"]["thread_id"]），不通过闭包捕获，
使 graph 可跨请求共享。

@author Color2333
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from langgraph.config import get_config, get_stream_writer
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

# 编译后的 graph 单例（thread_id 无关，可跨请求复用）
_compiled_graph: Any = None


def _make_action_id(thread_id: str, tool_call_id: str) -> str:
    """从 thread_id + tool_call_id 确定性派生 action_id。

    必须确定性：LangGraph 恢复时会重新执行 call_tools 节点，再次走 interrupt()
    分支（此时 interrupt 立即返回 resume 值不暂停），若 action_id 随机则与首次
    interrupt 时不一致，导致路由层 pending action 反查失败。
    """
    raw = f"{thread_id}:{tool_call_id}"
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return f"act_{digest[:8]}_{digest[8:16]}"


def _call_model(state: AgentState, model: PaperMindChatModel) -> dict:
    messages = state["messages"]
    # PaperMindChatModel 已 bind_tools；直接 invoke
    ai_msg = model.invoke(messages)
    return {"messages": [ai_msg]}


def _should_continue(state: AgentState) -> str:
    last = state["messages"][-1]
    # tool_calls 优先从顶层 .tool_calls（langchain 1.x），回退 additional_kwargs（旧版/流式聚合）
    tool_calls = getattr(last, "tool_calls", None) or (last.additional_kwargs or {}).get(
        "tool_calls"
    )
    return "tools" if tool_calls else END


def _call_tools(state: AgentState) -> dict:
    """工具节点：auto 直接执行，confirm 调 interrupt 暂停。

    thread_id 在运行时从 get_config() 读，不通过闭包捕获——让编译后的
    graph 可跨请求复用（性能优化：避免每请求 build_graph）。
    """
    ai_msg = state["messages"][-1]
    tool_calls = getattr(ai_msg, "tool_calls", None)
    if not tool_calls:
        tool_calls = (ai_msg.additional_kwargs or {}).get("tool_calls", [])

    # 运行时从 config 取 thread_id（configurable.thread_id）
    cfg = get_config()
    thread_id = (cfg.get("configurable") or {}).get("thread_id", "default")

    writer = None
    try:
        writer = get_stream_writer()
    except Exception:
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


def _build_default_model() -> PaperMindChatModel:
    """构建默认模型实例（bind_tools + usage 回调）。可跨请求复用。"""
    from packages.ai.agent_service import _record_agent_usage
    from packages.ai.tools import TOOL_REGISTRY

    model = PaperMindChatModel()
    model = model.bind_tools(TOOL_REGISTRY)
    object.__setattr__(model, "on_usage", _record_agent_usage)
    return model


def get_compiled_graph(checkpointer: Any) -> Any:
    """获取/构建编译后的 graph 单例（thread_id 无关，跨请求复用）。

    性能优化：避免每请求 build_graph。thread_id 在运行时从 config 读。
    checkpointer 变化时（MemorySaver→PostgresSaver）会重建。
    """
    global _compiled_graph
    if _compiled_graph is not None:
        return _compiled_graph

    model = _build_default_model()

    g = StateGraph(AgentState)
    g.add_node("agent", lambda state: _call_model(state, model))
    g.add_node("tools", _call_tools)
    g.set_entry_point("agent")
    g.add_conditional_edges("agent", _should_continue, {"tools": "tools", END: END})
    g.add_edge("tools", "agent")
    _compiled_graph = g.compile(checkpointer=checkpointer)
    logger.info("LangGraph compiled graph 已缓存（checkpointer=%s）", type(checkpointer).__name__)
    return _compiled_graph


def reset_compiled_graph_for_test() -> None:
    """测试用：重置编译后的 graph 单例。"""
    global _compiled_graph
    _compiled_graph = None


# 兼容旧调用（build_graph 仍可调，但内部走 get_compiled_graph）
def build_graph(
    checkpointer: Any, model: PaperMindChatModel | None = None, thread_id: str = "default"
):
    """构建并编译 ReAct graph。

    兼容入口：仍接受 model/thread_id 参数（测试用），但生产路径走
    get_compiled_graph() 单例复用。传 model 时走旧路径（每请求重建，单测用）。
    """
    if model is not None:
        # 单测路径：注入 mock model，每请求重建
        g = StateGraph(AgentState)
        g.add_node("agent", _build_agent_node_v1(model))
        g.add_node("tools", _build_tools_node_with_thread_id(thread_id, model))
        g.set_entry_point("agent")
        g.add_conditional_edges("agent", _should_continue, {"tools": "tools", END: END})
        g.add_edge("tools", "agent")
        return g.compile(checkpointer=checkpointer)

    return get_compiled_graph(checkpointer)


# ---------- 旧式闭包节点（单测 mock model 用，thread_id 通过闭包） ----------


def _build_agent_node_v1(model: PaperMindChatModel):
    def call_model(state: AgentState) -> dict:
        return _call_model(state, model)

    return call_model


def _build_tools_node_with_thread_id(thread_id: str, model: PaperMindChatModel):
    """单测用：thread_id 通过闭包捕获（绕过 get_config，测试图无 configurable）。"""

    def call_tools(state: AgentState) -> dict:
        ai_msg = state["messages"][-1]
        tool_calls = getattr(ai_msg, "tool_calls", None)
        if not tool_calls:
            tool_calls = (ai_msg.additional_kwargs or {}).get("tool_calls", [])

        writer = None
        try:
            writer = get_stream_writer()
        except Exception:
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
                resume_value = interrupt(
                    {
                        "tool": name,
                        "args": args,
                        "tool_call_id": tc_id,
                        "action_id": action_id,
                        "description": desc,
                    }
                )
                confirmed = bool(resume_value.get("confirmed"))
                if confirmed:
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
                tool_msg, _ = run_tool(tc_dict, writer)
                results.append(tool_msg)
        return {"messages": results}

    return call_tools


__all__ = [
    "build_graph",
    "get_compiled_graph",
    "reset_compiled_graph_for_test",
    "DEFAULT_RECURSION_LIMIT",
]
