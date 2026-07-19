"""PaperMindChatModel 单元测试 —— 验证 chunk 形状对齐 langchain 期望。

计划风险 #1：tool_call chunk 必须能被 graph 解析成 ai_msg.tool_calls。
@author Color2333
"""

from __future__ import annotations

from unittest.mock import MagicMock

from langchain_core.messages import AIMessageChunk, HumanMessage, SystemMessage, ToolMessage

from packages.integrations.llm_client import StreamEvent


def _fake_client(events: list[StreamEvent]) -> MagicMock:
    """构造一个 LLMClient mock，chat_stream 按给定事件序列 yield。"""
    client = MagicMock()
    client.provider = "xiaomi"
    client.chat_stream.return_value = iter(events)
    return client


def test_stream_text_delta_yields_content_chunk():
    from packages.langgraph_agent.chat_model import PaperMindChatModel

    model = PaperMindChatModel()
    object.__setattr__(
        model,
        "_client",
        _fake_client(
            [
                StreamEvent(type="text_delta", content="你好"),
                StreamEvent(type="text_delta", content="世界"),
                StreamEvent(type="done"),
            ]
        ),
    )
    chunks = list(model.stream([HumanMessage(content="hi")]))
    # 至少有 2 个 content chunk
    contents = [c.content for c in chunks if isinstance(c, AIMessageChunk) and c.content]
    assert "你好" in contents
    assert "世界" in contents


def test_stream_tool_call_yields_tool_call_chunk():
    """风险 #1 核心：tool_call 事件 → AIMessageChunk(tool_call_chunks=[...])，
    聚合后 AIMessage.additional_kwargs.tool_calls 可被 graph 读取。"""
    from packages.langgraph_agent.chat_model import PaperMindChatModel

    model = PaperMindChatModel()
    object.__setattr__(
        model,
        "_client",
        _fake_client(
            [
                StreamEvent(type="text_delta", content="让我搜索"),
                StreamEvent(
                    type="tool_call",
                    tool_call_id="call_abc",
                    tool_name="search_papers",
                    tool_arguments='{"keyword": "test", "limit": 5}',
                ),
                StreamEvent(type="done"),
            ]
        ),
    )
    # 聚合流式 chunk 成完整 AIMessage（langchain 标准做法）
    chunks = list(model.stream([HumanMessage(content="搜索 test")]))
    aggregated = AIMessageChunk(content="", tool_call_chunks=[])
    for c in chunks:
        aggregated = aggregated + c  # type: ignore[assignment]
    # 验证 tool_call 被聚合成 tool_call_chunks（args 是 JSON 字符串，langchain 流式协议）
    tcs = aggregated.tool_call_chunks or []
    assert len(tcs) == 1, f"应有 1 个 tool_call_chunk，实际 {len(tcs)}"
    assert tcs[0]["name"] == "search_papers"
    assert tcs[0]["id"] == "call_abc"
    # tool_call_chunks 的 args 是 JSON 字符串
    import json as _json

    args = _json.loads(tcs[0]["args"]) if isinstance(tcs[0]["args"], str) else tcs[0]["args"]
    assert args["keyword"] == "test", f"args 应可解析出 keyword=test，实际 {tcs[0]['args']!r}"


def test_invoke_aggregates_to_aimessage_with_tool_calls():
    """invoke 路径：_generate 聚合出 AIMessage，additional_kwargs.tool_calls 非空。"""
    from packages.langgraph_agent.chat_model import PaperMindChatModel

    model = PaperMindChatModel()
    object.__setattr__(
        model,
        "_client",
        _fake_client(
            [
                StreamEvent(type="text_delta", content="思考中"),
                StreamEvent(
                    type="tool_call",
                    tool_call_id="call_xyz",
                    tool_name="get_system_status",
                    tool_arguments="{}",
                ),
                StreamEvent(type="done"),
            ]
        ),
    )
    result = model.invoke([HumanMessage(content="状态")])
    assert result.content == "思考中"
    # tool_calls 是 AIMessage 顶层字段（langchain 1.x）
    tcs = result.tool_calls or result.additional_kwargs.get("tool_calls", [])
    assert len(tcs) == 1
    assert tcs[0]["name"] == "get_system_status"
    assert tcs[0]["id"] == "call_xyz"
    assert tcs[0]["args"] == {}


def test_bind_tools_transparently_passes_openai_spec():
    """风险 #3：bind_tools 应直接透传 OpenAI spec，不漂移描述。"""
    from packages.ai.tools import TOOL_REGISTRY
    from packages.langgraph_agent.chat_model import PaperMindChatModel

    model = PaperMindChatModel()
    # bind_tools 接受 ToolDef 列表
    bound = model.bind_tools(TOOL_REGISTRY)
    assert bound.tools is not None
    assert len(bound.tools) == len(TOOL_REGISTRY)
    # 验证第一个 tool 的 OpenAI spec 形状
    first = bound.tools[0]
    assert first["type"] == "function"
    assert "name" in first["function"]
    assert "description" in first["function"]
    assert "parameters" in first["function"]
    # 描述应与 ToolDef 原文一致（未注入 title 等额外字段）
    assert first["function"]["description"] == TOOL_REGISTRY[0].description


def test_usage_event_triggers_on_usage_callback():
    """usage 事件应触发 on_usage 回调（复用 _record_agent_usage 写 PromptTrace）。"""
    from packages.langgraph_agent.chat_model import PaperMindChatModel

    captured: list[tuple] = []
    model = PaperMindChatModel()
    object.__setattr__(model, "on_usage", lambda p, m, i, o: captured.append((p, m, i, o)))
    object.__setattr__(
        model,
        "_client",
        _fake_client(
            [
                StreamEvent(type="text_delta", content="ok"),
                StreamEvent(type="usage", model="mimo-v2.5", input_tokens=10, output_tokens=5),
                StreamEvent(type="done"),
            ]
        ),
    )
    list(model.stream([HumanMessage(content="hi")]))
    assert captured == [("xiaomi", "mimo-v2.5", 10, 5)], f"usage 回调应被触发，实际 {captured}"


def test_pm_messages_to_openai_preserves_tool_calls_and_tool_messages():
    """LangChain BaseMessage → OpenAI dict 转换保留 tool_calls 与 tool result 配对。"""
    from langchain_core.messages import AIMessage

    from packages.langgraph_agent.chat_model import _pm_messages_to_openai

    msgs = [
        SystemMessage(content="你是助手"),
        HumanMessage(content="搜索 test"),
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "search_papers",
                    "args": {"keyword": "test"},
                    "id": "tc1",
                    "type": "tool_call",
                }
            ],
        ),
        ToolMessage(content='{"success": true}', tool_call_id="tc1"),
    ]
    out = _pm_messages_to_openai(msgs)
    assert out[0] == {"role": "system", "content": "你是助手"}
    assert out[1] == {"role": "user", "content": "搜索 test"}
    # assistant 带 tool_calls
    assert out[2]["role"] == "assistant"
    tcs = out[2]["tool_calls"]
    assert tcs[0]["id"] == "tc1"
    assert tcs[0]["function"]["name"] == "search_papers"
    # arguments 应被序列化成 JSON 字符串（OpenAI 协议要求）
    assert isinstance(tcs[0]["function"]["arguments"], str)
    import json

    assert json.loads(tcs[0]["function"]["arguments"]) == {"keyword": "test"}
    # tool 消息
    assert out[3]["role"] == "tool"
    assert out[3]["tool_call_id"] == "tc1"
    assert out[3]["content"] == '{"success": true}'
