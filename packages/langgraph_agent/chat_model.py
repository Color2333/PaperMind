"""PaperMindChatModel —— 把现有 LLMClient.chat_stream 包成 LangChain BaseChatModel。

设计要点：
- 复用 packages.integrations.LLMClient 的 provider 路由（xiaomi/zhipu/openai/anthropic），
  不引入 langchain-openai / langchain-anthropic 依赖。
- chat_stream 的 text_delta → AIMessageChunk(content=...)
  chat_stream 的 tool_call → AIMessageChunk(tool_call_chunks=[...])
  chat_stream 的 usage   → 复用 _record_agent_usage 写 PromptTrace
- bind_tools 直接透传现有 get_openai_tools() 的 OpenAI function spec，
  不让 langchain 给 args_schema 注入 title 字段导致描述漂移（计划风险 #3）。

@author Color2333
"""

from __future__ import annotations

import contextlib
import json
from typing import TYPE_CHECKING, Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import ConfigDict

from packages.ai.tools import get_openai_tools
from packages.integrations.llm_client import LLMClient, StreamEvent

if TYPE_CHECKING:
    from collections.abc import Iterator

    from langchain_core.callbacks import CallbackManagerForLLMRun


def _pm_messages_to_openai(messages: list[BaseMessage]) -> list[dict]:
    """把 LangChain BaseMessage 转成 LLMClient.chat_stream 期望的 OpenAI dict 列表。"""
    out: list[dict] = []
    for m in messages:
        if m.type == "system":
            out.append({"role": "system", "content": m.content})
        elif m.type == "human":
            out.append({"role": "user", "content": m.content})
        elif m.type == "ai":
            entry: dict = {"role": "assistant"}
            if m.content:
                entry["content"] = m.content
            # tool_calls: langchain AIMessage 顶层字段 .tool_calls（list[ToolCall]），
            # 旧版本可能在 additional_kwargs；两处都查。
            tcs = m.tool_calls or (m.additional_kwargs or {}).get("tool_calls") or []
            if tcs:
                entry["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": tc["args"]
                            if isinstance(tc["args"], str)
                            else json.dumps(tc["args"], ensure_ascii=False),
                        },
                    }
                    for tc in tcs
                ]
            out.append(entry)
        elif m.type == "tool":
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": m.tool_call_id or "",
                    "content": m.content,
                }
            )
        else:
            out.append({"role": "user", "content": str(m.content)})
    return out


class PaperMindChatModel(BaseChatModel):
    """包装 LLMClient.chat_stream 的 LangChain ChatModel。

    绑定工具：用 bind_tools 直接把 OpenAI function spec 塞进 kwargs["tools"]，
    _stream/_generate 透传给 chat_stream(tools=...)。不走 langchain 的 tool 格式化。
    """

    # 可在实例化时注入（测试 mock 用），默认走真实 LLMClient
    _client: LLMClient | None = None
    max_tokens: int = 8192
    # 工具列表（OpenAI spec），由 bind_tools 注入
    tools: list[dict] | None = None
    # usage 回调（provider, model, input_tokens, output_tokens）→ None
    on_usage: Any = None

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @property
    def _llm_type(self) -> str:
        return "papermind"

    def _client_obj(self) -> LLMClient:
        if self._client is None:
            object.__setattr__(self, "_client", LLMClient())
        return self._client  # type: ignore[return-value]

    # ---------- 关键：bind_tools 透传现有 OpenAI spec ----------
    def bind_tools(self, tools: list, **kwargs: Any) -> BaseChatModel:  # type: ignore[override]
        """tools 期望是 ToolDef 列表或 OpenAI function spec 列表。
        为了不漂移描述，统一转成 OpenAI function spec 后存到 self.tools。
        """
        import copy

        clone = copy.copy(self)
        if tools and all(isinstance(t, dict) and "type" in t for t in tools):
            # 已经是 OpenAI spec（{"type":"function","function":{...}}）
            object.__setattr__(clone, "tools", tools)
        elif tools and all(hasattr(t, "name") and hasattr(t, "parameters") for t in tools):
            # ToolDef 列表 → 转 OpenAI spec（与 get_openai_tools() 同形）
            object.__setattr__(
                clone,
                "tools",
                [
                    {
                        "type": "function",
                        "function": {
                            "name": t.name,
                            "description": t.description,
                            "parameters": t.parameters,
                        },
                    }
                    for t in tools
                ],
            )
        else:
            # langchain StructuredTool 列表 → 用 ToolDef 风格提取
            object.__setattr__(
                clone,
                "tools",
                [
                    {
                        "type": "function",
                        "function": {
                            "name": t.name,
                            "description": t.description or "",
                            "parameters": getattr(t, "args_schema", {})
                            and t.args_schema.model_json_schema()
                            or {},
                        },
                    }
                    for t in tools
                ],
            )
        return clone

    # ---------- _stream：核心流式实现 ----------
    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        client = self._client_obj()
        openai_msgs = _pm_messages_to_openai(messages)
        # tool_call 累积器：按 index 聚合增量 arguments
        # chat_stream 的 tool_call StreamEvent 是"完整一次性"（_chat_stream_openai_compatible
        # 在流结束后一次性 yield 每个完整 tool_call），所以这里不需要增量聚合，
        # 直接在每个 tool_call 事件转成单个 AIMessageChunk。
        for event in client.chat_stream(
            openai_msgs,
            tools=self.tools,
            max_tokens=self.max_tokens,
        ):
            assert isinstance(event, StreamEvent)
            if event.type == "text_delta" and event.content:
                chunk = AIMessageChunk(content=event.content)
                yield ChatGenerationChunk(message=chunk)
                if run_manager:
                    run_manager.on_llm_new_token(event.content, chunk=chunk)
            elif event.type == "tool_call":
                # 解析 args（chat_stream 已保证是合法 JSON 字符串或空）
                # 注意：langchain AIMessageChunk.tool_call_chunks[].args 必须是 JSON 字符串
                # （增量协议），聚合后 langchain 自动解析成 dict 存到 tool_calls[].args。
                args_str = event.tool_arguments if event.tool_arguments else "{}"
                tc_chunk = {
                    "name": event.tool_name,
                    "args": args_str,
                    "id": event.tool_call_id,
                    "type": "tool_call_chunk",
                    "index": 0,
                }
                chunk = AIMessageChunk(content="", tool_call_chunks=[tc_chunk])
                gen = ChatGenerationChunk(message=chunk)
                yield gen
                if run_manager:
                    run_manager.on_llm_new_token("", chunk=chunk)
            elif event.type == "usage":
                if self.on_usage:
                    with contextlib.suppress(Exception):
                        self.on_usage(
                            client.provider,
                            event.model or "",
                            event.input_tokens or 0,
                            event.output_tokens or 0,
                        )
            elif event.type == "error":
                # error 事件转成 content 为错误信息的 chunk，便于上层 SSE 发 error 事件
                chunk = AIMessageChunk(content=f"[error] {event.content}")
                yield ChatGenerationChunk(message=chunk)
            # done: 不 yield 任何 chunk，由 chat_stream 内部结束信号

    # ---------- _generate：非流式（聚合 _stream）----------
    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        text_buf = ""
        tool_calls: list[dict] = []
        for chunk in self._stream(messages, stop=stop, run_manager=run_manager, **kwargs):
            msg = chunk.message
            if msg.content:
                text_buf += msg.content
            if msg.tool_call_chunks:
                for tc in msg.tool_call_chunks:
                    # tc["args"] 是 JSON 字符串（langchain 流式协议），解析成 dict
                    raw_args = tc["args"]
                    if isinstance(raw_args, str):
                        try:
                            parsed_args = json.loads(raw_args) if raw_args else {}
                        except (json.JSONDecodeError, TypeError):
                            parsed_args = {}
                    else:
                        parsed_args = raw_args or {}
                    tool_calls.append(
                        {
                            "name": tc["name"],
                            "args": parsed_args,
                            "id": tc["id"],
                            "type": "tool_call",
                        }
                    )
        # AIMessage.tool_calls 是顶层字段（langchain 1.x），直接传让 pydantic 校验。
        # additional_kwargs 仅用于 OpenAI dict 重建（_pm_messages_to_openai 优先读 tool_calls）。
        ai = AIMessage(
            content=text_buf,
            tool_calls=tool_calls if tool_calls else [],
        )
        return ChatResult(generations=[ChatGeneration(message=ai)])


__all__ = ["PaperMindChatModel", "get_openai_tools"]
