"""
AgentCore Loop — 显式 Agent 循环，参考 learn-claude-code s01/s02

核心模式（s01）：
    while stop_reason == "tool_use":
        response = LLM(messages, tools)
        execute tools
        append results

这个模块是整个 Agent Harness 的心脏。
Model 决定何时调用工具，何时停止。
Code 只负责：执行工具、收集结果、注入回 messages。

                        ┌──────────────────────────────────────┐
                        │  messages[] (对话历史)               │
                        │  system (角色/上下文)                 │
                        │  tools (可用工具列表)                 │
                        └──────────┬───────────────────────────┘
                                   │ client.messages.create()
                                   ▼
                         ┌─────────────────────┐
                         │       LLM           │
                         │ (Anthropic/OpenAI) │
                         └──────────┬──────────┘
                                    │ response
                        stop_reason == "tool_use"?
                                   │
                         ┌─────────┴─────────┐
                         │ yes               │ no
                         ▼                   ▼
               ┌─────────────────┐      ┌──────────┐
               │ for each block │      │  return  │
               │ tool_use:      │      │  text    │
               │   execute()    │      └──────────┘
               │   append result│
               │ loop back ─────┼──→ messages.append(result)
               └─────────────────┘
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, cast

from anthropic import Anthropic

if TYPE_CHECKING:
    from anthropic.types import MessageParam

    from .dispatcher import ToolDispatcher


class StopReason(Enum):
    TOOL_USE = "tool_use"
    END_TURN = "end_turn"
    MAX_TOKENS = "max_tokens"
    UNKNOWN = "unknown"


@dataclass
class ToolResult:
    tool_use_id: str
    name: str
    output: str | Exception
    duration_ms: float | None = None


@dataclass
class AgentResponse:
    text: str | None
    stop_reason: StopReason
    tool_results: list[ToolResult]
    raw: Any = None


# -- Tool Definition (Anthropic format) --
ToolDef = dict[str, Any]
ToolHandler = Callable[..., str | dict[str, Any]]


@dataclass
class AgentConfig:
    model: str
    system_prompt: str
    max_tokens: int = 8192
    timeout_seconds: int = 120
    max_loop_iterations: int = 500


class AgentLoop:
    """
    显式 Agent 循环类。

    使用方式：
        config = AgentConfig(
            model="claude-sonnet-4-20250514",
            system_prompt="You are a coding agent...",
        )
        dispatcher = ToolDispatcher()
        dispatcher.register("bash", bash_handler)
        dispatcher.register("read_file", read_handler)

        loop = AgentLoop(config, dispatcher)
        result = loop.run([{"role": "user", "content": "帮我写一个 hello world"}])
    """

    def __init__(self, config: AgentConfig, dispatcher: ToolDispatcher):
        self.config = config
        self.dispatcher = dispatcher
        self._iteration_count = 0

    def run(self, messages: list[dict[str, Any]]) -> AgentResponse:
        """
        执行 Agent 循环，直到 LLM 停止调用工具。
        返回最终响应（含所有工具结果）。
        """
        self._iteration_count = 0
        tool_results: list[ToolResult] = []

        while True:
            self._iteration_count += 1
            if self._iteration_count > self.config.max_loop_iterations:
                raise RuntimeError(
                    f"Agent loop exceeded max iterations ({self.config.max_loop_iterations}). "
                    "Possible infinite loop or very long task."
                )

            response = self._call_llm(messages)
            stop_reason = self._parse_stop_reason(response)

            if stop_reason != StopReason.TOOL_USE:
                return AgentResponse(
                    text=self._extract_text(response),
                    stop_reason=stop_reason,
                    tool_results=tool_results,
                    raw=response,
                )

            # 执行所有工具调用
            batch_results: list[ToolResult] = []
            for block in self._iter_tool_blocks(response):
                result = self._execute_tool(block)
                batch_results.append(result)

            tool_results.extend(batch_results)

            # 把工具结果注入 messages，继续循环
            messages.append({"role": "assistant", "content": response.content})
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": r.tool_use_id,
                            "content": self._safe_output(r.output),
                        }
                        for r in batch_results
                    ],
                }
            )

    def _call_llm(self, messages: list[dict[str, Any]]) -> Any:
        client = Anthropic()
        tool_defs = self.dispatcher.get_tool_definitions()

        response = client.messages.create(
            model=self.config.model,
            system=self.config.system_prompt,
            messages=cast("list[MessageParam]", messages),
            tools=tool_defs,
            max_tokens=self.config.max_tokens,
        )
        return response

    _STOP_REASON_MAP = {
        "tool_use": StopReason.TOOL_USE,
        "end_turn": StopReason.END_TURN,
        "max_tokens": StopReason.MAX_TOKENS,
    }

    def _parse_stop_reason(self, response: Any) -> StopReason:
        sr = getattr(response, "stop_reason", None) or ""
        return self._STOP_REASON_MAP.get(sr, StopReason.UNKNOWN)

    def _iter_tool_blocks(self, response: Any):
        """遍历 response 中所有 tool_use 块"""
        if hasattr(response, "content"):
            for block in response.content:
                if hasattr(block, "type") and block.type == "tool_use":
                    yield block

    def _execute_tool(self, block) -> ToolResult:
        """执行单个工具调用"""
        name = block.name
        args = block.input
        start = time.time()

        try:
            output = self.dispatcher.dispatch(name, **args)
        except Exception as exc:  # noqa: BLE001
            output = exc

        duration_ms = (time.time() - start) * 1000
        return ToolResult(
            tool_use_id=block.id,
            name=name,
            output=output,
            duration_ms=duration_ms,
        )

    def _extract_text(self, response: Any) -> str | None:
        if hasattr(response, "content"):
            parts = []
            for block in response.content:
                if hasattr(block, "type") and block.type == "text":
                    parts.append(block.text)
            return "\n".join(parts) if parts else None
        return None

    @staticmethod
    def _safe_output(output: str | Exception) -> str:
        if isinstance(output, Exception):
            return f"Error: {type(output).__name__}: {output}"
        return str(output)[:100_000]  # 防止 context 溢出


# -- Convenience: 单轮对话快捷函数 --
def chat(
    system_prompt: str,
    user_message: str,
    model: str = "claude-sonnet-4-20250514",
    tools: dict[str, ToolHandler] | None = None,
) -> AgentResponse:
    """
    单轮对话快捷函数。
    内部创建 AgentLoop，执行一轮完整循环，返回最终响应。
    """
    from .dispatcher import ToolDispatcher

    config = AgentConfig(model=model, system_prompt=system_prompt)
    dispatcher = ToolDispatcher()

    if tools:
        for name, handler in tools.items():
            dispatcher.register(name, handler)

    loop = AgentLoop(config, dispatcher)
    messages = [{"role": "user", "content": user_message}]
    return loop.run(messages)
