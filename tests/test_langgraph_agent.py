"""LangGraph agent 集成测试：graph + interrupt + SSE 适配。

验证：
- auto 工具：graph 跑通，SSE 产出 text_delta/tool_start/tool_result/done
- confirm 工具：interrupt 产出 action_confirm，Command(resume={"confirmed":True}) 恢复后 action_result
- reject：Command(resume={"confirmed":False}) → action_result(success=False)
- SSE 9 事件类型对齐前端协议

计划风险 #2：get_stream_writer() 在同步节点里可用（stream_mode="custom" 能消费）。
@author Color2333
"""

from __future__ import annotations

import contextlib
import json
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command

from packages.integrations.llm_client import StreamEvent

if TYPE_CHECKING:
    from collections.abc import Iterator


def _parse_sse_events(sse_iter: Iterator[str]) -> list[tuple[str, dict]]:
    """解析 SSE 事件流成 [(event_type, data), ...]。"""
    import re

    events = []
    pattern = re.compile(r"event:\s*(\S+)\s*\ndata:\s*(\{.*?\})\s*\n\n", re.DOTALL)
    buf = ""
    for chunk in sse_iter:
        buf += chunk
        for match in pattern.finditer(buf):
            with contextlib.suppress(json.JSONDecodeError):
                events.append((match.group(1), json.loads(match.group(2))))
        buf = buf[buf.rfind("\n\n") + 2 :] if "\n\n" in buf else buf
    # 处理剩余
    for match in pattern.finditer(buf):
        with contextlib.suppress(json.JSONDecodeError):
            events.append((match.group(1), json.loads(match.group(2))))
    return events


def _make_mock_model(events_per_call: list[list[StreamEvent]]) -> Any:
    """构造一个 mock PaperMindChatModel，每次 invoke 按顺序消费 events_per_call。

    用子类重写 _generate（pydantic 模型实例属性赋值不会覆盖类方法派发）。
    langchain invoke 优先走 _stream（见 _generate_with_cache），故同时重写 _stream。
    """
    from packages.langgraph_agent.chat_model import PaperMindChatModel

    call_log: list[list[StreamEvent]] = list(events_per_call)

    class _MockModel(PaperMindChatModel):
        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            events = call_log.pop(0) if call_log else [StreamEvent(type="done")]
            text = ""
            tcs = []
            for ev in events:
                if ev.type == "text_delta":
                    text += ev.content
                elif ev.type == "tool_call":
                    try:
                        args = json.loads(ev.tool_arguments) if ev.tool_arguments else {}
                    except (json.JSONDecodeError, TypeError):
                        args = {}
                    tcs.append(
                        {
                            "name": ev.tool_name,
                            "args": args,
                            "id": ev.tool_call_id,
                            "type": "tool_call",
                        }
                    )
            # tool_calls 是 AIMessage 顶层字段（langchain 1.x）
            ai = AIMessage(content=text, tool_calls=tcs if tcs else [])
            return ChatResult(generations=[ChatGeneration(message=ai)])

        def _stream(self, messages, stop=None, run_manager=None, **kwargs):
            # langchain invoke 优先走 _stream；必须重写否则会调真实 LLMClient.chat_stream。
            # 这里把 _generate 的结果拆成 ChatGenerationChunk（text + tool_call_chunk）。
            result = self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)
            ai = result.generations[0].message
            if ai.content:
                yield ChatGenerationChunk(message=AIMessageChunk(content=ai.content))
            for tc in ai.tool_calls or []:
                args_str = (
                    tc["args"]
                    if isinstance(tc["args"], str)
                    else json.dumps(tc["args"], ensure_ascii=False)
                )
                yield ChatGenerationChunk(
                    message=AIMessageChunk(
                        content="",
                        tool_call_chunks=[
                            {
                                "name": tc["name"],
                                "args": args_str,
                                "id": tc["id"],
                                "type": "tool_call_chunk",
                                "index": 0,
                            }
                        ],
                    )
                )

        def bind_tools(self, tools, **kwargs):  # type: ignore[override]
            return self

    model = _MockModel()
    return model


def _build_test_graph(model: Any, thread_id: str = "test-thread") -> Any:
    """复用 build_graph 但注入 mock model。"""
    from packages.langgraph_agent.graph import build_graph

    cp = MemorySaver()
    return build_graph(cp, model=model, thread_id=thread_id)


class TestAutoToolFlow:
    """auto 工具：完整 ReAct 一轮。"""

    def test_search_papers_full_flow(self, monkeypatch):
        """LLM 调 search_papers（auto 工具），graph 执行后 LLM 给最终回复。"""
        # 第一轮：LLM 返回 tool_call(search_papers)
        # 第二轮：LLM 看到 tool result，返回纯文本
        model = _make_mock_model(
            [
                [
                    StreamEvent(type="text_delta", content="让我搜索"),
                    StreamEvent(
                        type="tool_call",
                        tool_call_id="tc_search",
                        tool_name="search_papers",
                        tool_arguments='{"keyword": "test"}',
                    ),
                ],
                [StreamEvent(type="text_delta", content="搜索完成")],
            ]
        )
        graph = _build_test_graph(model)

        # mock run_tool 的 execute_tool_stream，避免真查 DB
        from packages.ai.tools import ToolProgress, ToolResult
        from packages.langgraph_agent import tools_adapter

        def fake_execute(name, args):
            yield ToolProgress(message="搜索中", current=1, total=1)
            yield ToolResult(success=True, data={"papers": [], "count": 0}, summary="搜索到 0 篇")

        monkeypatch.setattr(tools_adapter, "execute_tool_stream", fake_execute)

        config = {"configurable": {"thread_id": "t1"}, "recursion_limit": 24}
        from packages.langgraph_agent.sse_adapter import stream_to_sse

        sse_iter = stream_to_sse(graph, {"messages": [HumanMessage(content="搜索 test")]}, config)
        events = _parse_sse_events(sse_iter)
        types = [t for t, _ in events]

        # 期望事件序列：text_delta(让我搜索) + tool_start + tool_progress + tool_result + text_delta(搜索完成) + done
        assert "text_delta" in types
        assert "tool_start" in types
        assert "tool_progress" in types
        assert "tool_result" in types
        assert "done" in types
        # tool_start 的 data
        ts = next(d for t, d in events if t == "tool_start")
        assert ts["name"] == "search_papers"
        assert ts["id"] == "tc_search"
        # tool_result 的 data
        tr = next(d for t, d in events if t == "tool_result")
        assert tr["name"] == "search_papers"
        assert tr["success"] is True


class TestConfirmToolFlow:
    """confirm 工具：interrupt + resume。"""

    def test_confirm_interrupt_then_resume(self, monkeypatch):
        """LLM 调 skim_paper（confirm），graph interrupt 发 action_confirm，
        Command(resume={"confirmed":True}) 恢复后发 action_result。"""
        model = _make_mock_model(
            [
                [
                    StreamEvent(
                        type="tool_call",
                        tool_call_id="tc_skim",
                        tool_name="skim_paper",
                        tool_arguments='{"paper_id": "p1"}',
                    ),
                ],
                # resume 后第二轮：LLM 看到 action result，给最终回复
                [StreamEvent(type="text_delta", content="粗读完成")],
            ]
        )
        graph = _build_test_graph(model)

        from packages.ai.tools import ToolResult
        from packages.langgraph_agent import tools_adapter

        def fake_execute(name, args):
            yield ToolResult(success=True, data={"one_liner": "test"}, summary="粗读完成")

        monkeypatch.setattr(tools_adapter, "execute_tool_stream", fake_execute)

        config = {"configurable": {"thread_id": "t_confirm"}, "recursion_limit": 24}
        from packages.langgraph_agent.sse_adapter import stream_to_sse

        # 第一轮：应 interrupt
        sse_iter = stream_to_sse(graph, {"messages": [HumanMessage(content="粗读 p1")]}, config)
        events = _parse_sse_events(sse_iter)
        types = [t for t, _ in events]

        assert "action_confirm" in types, f"应产出 action_confirm，实际 {types}"
        ac = next(d for t, d in events if t == "action_confirm")
        assert ac["tool"] == "skim_paper"
        assert ac["args"] == {"paper_id": "p1"}
        assert "id" in ac
        # interrupt 后不应有 done（与老 loop 一致：action_confirm 后流暂停）
        # 但 sse_adapter 在 stream 结束后会发 done；interrupt 会结束 stream，所以 done 会出现
        # 这是与老 loop 的细微差异，前端可接受（done 后无后续）

        # 第二轮：Command(resume={"confirmed": True}) 恢复
        sse_iter2 = stream_to_sse(
            graph, Command(resume={"confirmed": True, "action_id": ac["id"]}), config
        )
        events2 = _parse_sse_events(sse_iter2)
        types2 = [t for t, _ in events2]

        assert "action_result" in types2, f"resume 后应发 action_result，实际 {types2}"
        ar = next(d for t, d in events2 if t == "action_result")
        assert ar["success"] is True
        assert "id" in ar
        # resume 后 LLM 继续给文本
        assert "text_delta" in types2

    def test_reject_resume(self, monkeypatch):
        """reject：Command(resume={"confirmed":False}) → action_result(success=False)。"""
        model = _make_mock_model(
            [
                [
                    StreamEvent(
                        type="tool_call",
                        tool_call_id="tc_skim2",
                        tool_name="skim_paper",
                        tool_arguments='{"paper_id": "p2"}',
                    ),
                ],
                # reject 后 LLM 给替代方案
                [StreamEvent(type="text_delta", content="好的，不粗读了")],
            ]
        )
        graph = _build_test_graph(model)

        config = {"configurable": {"thread_id": "t_reject"}, "recursion_limit": 24}
        from packages.langgraph_agent.sse_adapter import stream_to_sse

        # 先 interrupt
        sse_iter = stream_to_sse(graph, {"messages": [HumanMessage(content="粗读 p2")]}, config)
        events = _parse_sse_events(sse_iter)
        ac = next(d for t, d in events if t == "action_confirm")

        # reject
        sse_iter2 = stream_to_sse(
            graph, Command(resume={"confirmed": False, "action_id": ac["id"]}), config
        )
        events2 = _parse_sse_events(sse_iter2)
        types2 = [t for t, _ in events2]

        assert "action_result" in types2
        ar = next(d for t, d in events2 if t == "action_result")
        assert ar["success"] is False
        assert "用户已取消" in ar["summary"]
        # LLM 应继续给替代回复
        assert "text_delta" in types2


class TestSSEProtocolAlignment:
    """验证 SSE 事件类型与前端 SSEEventType 对齐。"""

    def test_all_emitted_event_types_are_in_frontend_union(self, monkeypatch):
        """所有产出的事件类型必须在前端 SSEEventType 联合类型里。"""
        frontend_types = {
            "conversation_init",
            "text_delta",
            "tool_start",
            "tool_result",
            "tool_progress",
            "action_confirm",
            "action_result",
            "done",
            "error",
        }
        model = _make_mock_model(
            [
                [
                    StreamEvent(type="text_delta", content="hi"),
                    StreamEvent(
                        type="tool_call",
                        tool_call_id="tc_gss",
                        tool_name="get_system_status",
                        tool_arguments="{}",
                    ),
                ],
                [StreamEvent(type="text_delta", content="done")],
            ]
        )
        graph = _build_test_graph(model)

        from packages.ai.tools import ToolResult
        from packages.langgraph_agent import tools_adapter

        monkeypatch.setattr(
            tools_adapter,
            "execute_tool_stream",
            lambda n, a: iter([ToolResult(success=True, data={}, summary="ok")]),
        )

        config = {"configurable": {"thread_id": "t_proto"}, "recursion_limit": 24}
        from packages.langgraph_agent.sse_adapter import stream_to_sse

        events = _parse_sse_events(
            stream_to_sse(graph, {"messages": [HumanMessage(content="状态")]}, config)
        )
        types = {t for t, _ in events}
        extra = types - frontend_types
        assert not extra, f"产出了前端未定义的事件类型: {extra}"


class TestMaxRecursion:
    """recursion_limit 耗尽 → text_delta 提示 + done（与老 loop ⑩ 一致）。"""

    def test_recursion_exhausted_emits_notice(self, monkeypatch):
        """LLM 每轮都返回 tool_call，recursion_limit 耗尽时应有提示而非静默。"""
        # 每轮都返回 tool_call（无限循环）
        endless_events = [
            StreamEvent(
                type="tool_call",
                tool_call_id=f"tc_{i}",
                tool_name="get_system_status",
                tool_arguments="{}",
            )
            for i in range(50)
        ]
        # _make_mock_model 每次 invoke 消费一组事件；这里每组一个 tool_call
        model = _make_mock_model([[ev] for ev in endless_events])
        graph = _build_test_graph(model)

        from packages.ai.tools import ToolResult
        from packages.langgraph_agent import tools_adapter

        monkeypatch.setattr(
            tools_adapter,
            "execute_tool_stream",
            lambda n, a: iter([ToolResult(success=True, data={}, summary="ok")]),
        )

        # 极小 recursion_limit 触发耗尽
        config = {"configurable": {"thread_id": "t_rec"}, "recursion_limit": 4}
        from packages.langgraph_agent.sse_adapter import stream_to_sse

        events = _parse_sse_events(
            stream_to_sse(graph, {"messages": [HumanMessage(content="loop")]}, config)
        )
        types = [t for t, _ in events]
        assert "done" in types
        # 应有最大轮次提示（⑩ 同形）
        notices = [
            d for t, d in events if t == "text_delta" and "最大对话轮次" in d.get("content", "")
        ]
        assert len(notices) >= 1, (
            f"recursion 耗尽应有提示，实际 text_delta: {[d for t, d in events if t == 'text_delta']}"
        )


class TestEntryPoints:
    """entry.py 的 stream_chat_v2 入口（用 MemorySaver + mock model）。"""

    def test_stream_chat_v2_returns_sse_iter_and_conversation_id(self, monkeypatch):
        from packages.langgraph_agent import checkpointer, entry

        # 强制 MemorySaver
        monkeypatch.setattr(checkpointer, "_saver", MemorySaver())
        monkeypatch.setattr(checkpointer, "get_checkpointer", lambda: MemorySaver())

        _make_mock_model([[StreamEvent(type="text_delta", content="你好")]])
        monkeypatch.setattr(
            "packages.langgraph_agent.graph.build_graph",
            lambda cp, model=None, thread_id="default": _build_test_graph(
                model or model, thread_id
            ),
        )

        # mock _build_messages 避免真查 DB（system prompt + profile）
        monkeypatch.setattr(
            "packages.ai.agent_service._build_messages",
            lambda msgs: [{"role": "system", "content": "你是助手"}] + msgs,
        )

        sse_iter, cid = entry.stream_chat_v2(
            [{"role": "user", "content": "hi"}], conversation_id="conv-test-123"
        )
        assert cid == "conv-test-123"
        events = _parse_sse_events(sse_iter)
        types = [t for t, _ in events]
        assert "text_delta" in types
        assert "done" in types
