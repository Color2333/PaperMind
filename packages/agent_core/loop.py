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

import json
import logging
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, cast
from uuid import uuid4

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


# =============================================================================
# PaperMind 适配层：流式 Agent 循环 + 确认机制
# =============================================================================

if TYPE_CHECKING:
    from packages.integrations.llm_client import LLMClient, StreamEvent

logger = logging.getLogger(__name__)


def _make_sse(event: str, data: dict) -> str:
    """格式化 SSE 事件"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@dataclass
class PaperMindToolResult:
    """PaperMind 风格的工具结果"""

    success: bool
    data: dict = field(default_factory=dict)
    summary: str = ""


@dataclass
class PaperMindToolProgress:
    """PaperMind 风格的工具进度"""

    message: str
    current: int = 0
    total: int = 0


@dataclass
class PaperMindToolCall:
    """解析后的工具调用"""

    tool_call_id: str
    tool_name: str
    arguments: dict


class ConfirmationMixin:
    """
    混入类：处理需要确认的工具的 pending 流程。
    接管 _CONFIRM_TOOLS 逻辑，持久化到数据库。
    """

    def __init__(
        self,
        confirm_tools: set[str],
        pending_repo_class: type | None,
        session_scope: Callable,
    ):
        self._confirm_tools = confirm_tools
        self._pending_repo_class = pending_repo_class
        self._session_scope = session_scope
        self._action_ttl = 1800  # 30 分钟

    def is_confirm_tool(self, tool_name: str) -> bool:
        return tool_name in self._confirm_tools

    def store_pending_action(
        self,
        action_id: str,
        tool_name: str,
        tool_args: dict,
        tool_call_id: str,
        conversation_state: dict,
    ) -> None:
        """持久化 pending action 到数据库"""
        from packages.storage.repositories import AgentPendingActionRepository

        try:
            with self._session_scope() as session:
                repo = AgentPendingActionRepository(session)
                repo.create(
                    action_id=action_id,
                    tool_name=tool_name,
                    tool_args=tool_args,
                    tool_call_id=tool_call_id,
                    conversation_state=conversation_state,
                )
        except Exception as exc:
            logger.warning("存储 pending_action 失败: %s", exc)

    def load_pending_action(self, action_id: str) -> dict | None:
        """从数据库加载 pending action"""
        from packages.storage.repositories import AgentPendingActionRepository

        try:
            with self._session_scope() as session:
                repo = AgentPendingActionRepository(session)
                record = repo.get_by_id(action_id)
                if record:
                    return {
                        "tool": record.tool_name,
                        "args": record.tool_args,
                        "tool_call_id": record.tool_call_id,
                        "conversation": (record.conversation_state or {}).get("conversation", []),
                    }
        except Exception as exc:
            logger.warning("读取 pending_action 失败: %s", exc)
        return None

    def delete_pending_action(self, action_id: str) -> None:
        """从数据库删除 pending action"""
        from packages.storage.repositories import AgentPendingActionRepository

        try:
            with self._session_scope() as session:
                repo = AgentPendingActionRepository(session)
                repo.delete(action_id)
        except Exception as exc:
            logger.warning("删除 pending_action 失败: %s", exc)

    def cleanup_expired_actions(self) -> None:
        """清理过期的 pending actions"""
        from packages.storage.repositories import AgentPendingActionRepository

        try:
            with self._session_scope() as session:
                repo = AgentPendingActionRepository(session)
                deleted = repo.cleanup_expired(self._action_ttl)
                if deleted > 0:
                    logger.info("清理 %d 个过期 pending_actions", deleted)
        except Exception as exc:
            logger.warning("清理过期 pending_actions 失败: %s", exc)

    def describe_action(self, tool_name: str, args: dict) -> str:
        """生成操作描述"""
        descriptions: dict[str, Callable[[dict], str]] = {
            "ingest_arxiv": lambda a: (
                f"入库选中的 {len(a.get('arxiv_ids', []))} 篇论文（来源: {a.get('query', '?')}）"
            ),
            "skim_paper": lambda a: f"对论文 {a.get('paper_id', '?')[:8]}... 执行粗读分析",
            "deep_read_paper": lambda a: f"对论文 {a.get('paper_id', '?')[:8]}... 执行精读分析",
            "embed_paper": lambda a: f"对论文 {a.get('paper_id', '?')[:8]}... 执行向量化嵌入",
            "generate_wiki": lambda a: (
                f"生成 {a.get('type', '?')} 类型 Wiki（{a.get('keyword_or_id', '?')}）"
            ),
            "generate_daily_brief": lambda _: "生成每日研究简报",
            "manage_subscription": lambda a: (
                f"{'启用' if a.get('enabled') else '关闭'}主题「{a.get('topic_name', '?')}」的定时搜集"
            ),
        }
        fn = descriptions.get(tool_name)
        if fn:
            return fn(args)
        return f"执行 {tool_name}"


class StreamingAgentLoop:
    """
    PaperMind 流式 Agent 循环。

    支持：
    - LLMClient 流式输出（text_delta 事件）
    - 工具调用处理（tool_call 事件）
    - SSE 事件输出
    - 确认类工具的 pending 流程

    使用方式：
        loop = StreamingAgentLoop(
            llm=LLMClient(),
            tools=openai_tools_format,
            tool_registry=TOOL_REGISTRY,  # list[ToolDef]
            execute_fn=execute_tool_stream,  # Iterator[ToolProgress | ToolResult]
            session_scope=session_scope,
        )
        for sse in loop.run(conversation):
            yield sse
    """

    def __init__(
        self,
        llm: LLMClient,
        tools: list[dict],
        tool_registry: list[Any],  # list[ToolDef]
        execute_fn: Callable[[str, dict], Iterator],
        session_scope: Callable,
        max_rounds: int = 12,
        max_tokens: int = 8192,
        on_usage: Callable[[str, str, int, int], None] | None = None,
    ):
        self.llm = llm
        self.tools = tools
        self.execute_fn = execute_fn
        self.max_rounds = max_rounds
        self.max_tokens = max_tokens
        self._on_usage = on_usage

        # 从 tool_registry 提取 requires_confirm 集合
        confirm_names = {t.name for t in tool_registry if getattr(t, "requires_confirm", False)}
        self._confirm_mixin = ConfirmationMixin(
            confirm_tools=confirm_names,
            pending_repo_class=None,  # not needed directly
            session_scope=session_scope,
        )

    def run(self, conversation: list[dict]) -> Iterator[str]:
        """
        执行流式 Agent 循环，yield SSE 事件字符串。
        """
        for _round_idx in range(self.max_rounds):
            # 构建消息
            openai_msgs = self._build_messages(conversation)
            text_buf = ""
            tool_calls: list[PaperMindToolCall] = []

            # 流式 LLM 调用
            for event in self.llm.chat_stream(
                openai_msgs, tools=self.tools, max_tokens=self.max_tokens
            ):
                sse = self._handle_stream_event(event, text_buf=text_buf, tool_calls=tool_calls)
                if sse:
                    yield sse
                # 实时更新 text_buf
                if event.type == "text_delta":
                    text_buf += event.content

            # 没有工具调用 → 对话结束
            if not tool_calls:
                yield _make_sse("done", {})
                return

            # 记录 assistant 回复（含 tool_calls）
            assistant_msg = self._build_assistant_message(text_buf, tool_calls)
            conversation.append(assistant_msg)

            # 处理工具调用：自动工具 vs 确认工具
            confirm_calls = [
                tc for tc in tool_calls if self._confirm_mixin.is_confirm_tool(tc.tool_name)
            ]
            auto_calls = [
                tc for tc in tool_calls if not self._confirm_mixin.is_confirm_tool(tc.tool_name)
            ]

            # 执行自动工具
            for tc in auto_calls:
                for sse in self._execute_and_emit(tc, conversation):
                    yield sse

            # 有确认工具时，pending 并暂停
            if confirm_calls:
                tc = confirm_calls[0]
                yield from self._handle_confirm_tool(tc, conversation)
                return

        yield _make_sse("done", {})

    def _handle_stream_event(
        self,
        event: StreamEvent,
        text_buf: str,
        tool_calls: list[PaperMindToolCall],
    ) -> str | None:
        """处理单个流事件，返回 SSE 字符串或 None"""
        if event.type == "text_delta":
            return _make_sse("text_delta", {"content": event.content})
        elif event.type == "tool_call":
            tool_calls.append(
                PaperMindToolCall(
                    tool_call_id=event.tool_call_id,
                    tool_name=event.tool_name,
                    arguments=json.loads(event.tool_arguments) if event.tool_arguments else {},
                )
            )
        elif event.type == "error":
            return _make_sse("error", {"message": event.content})
        elif event.type == "usage" and self._on_usage:
            self._on_usage(
                event.model or "",
                event.model or "",
                event.input_tokens or 0,
                event.output_tokens or 0,
            )
        return None

    def _execute_and_emit(
        self,
        tc: PaperMindToolCall,
        conversation: list[dict],
    ) -> Iterator[str]:
        """执行工具并 yield SSE 事件"""
        # tool_start
        yield _make_sse(
            "tool_start",
            {
                "id": tc.tool_call_id,
                "name": tc.tool_name,
                "args": tc.arguments,
            },
        )

        result = PaperMindToolResult(success=False, summary="无结果")
        for item in self.execute_fn(tc.tool_name, tc.arguments):
            if isinstance(item, PaperMindToolProgress):
                yield _make_sse(
                    "tool_progress",
                    {
                        "id": tc.tool_call_id,
                        "message": item.message,
                        "current": item.current,
                        "total": item.total,
                    },
                )
            elif isinstance(item, PaperMindToolResult):
                result = PaperMindToolResult(
                    success=item.success, data=item.data, summary=item.summary
                )
            elif hasattr(item, "success") and hasattr(item, "data") and hasattr(item, "summary"):
                # agent_tools.ToolResult (不同模块的同名类)
                result = PaperMindToolResult(
                    success=item.success,
                    data=item.data if item.data else {},
                    summary=item.summary,
                )

        # 构建 tool 消息
        tool_content: dict = {
            "success": result.success,
            "summary": result.summary,
            "data": result.data,
        }
        if not result.success:
            tool_content["error_hint"] = (
                "工具执行失败。请分析原因，告知用户，并建议替代方案。不要用相同参数重试。"
            )

        conversation.append(
            {
                "role": "tool",
                "tool_call_id": tc.tool_call_id,
                "content": json.dumps(tool_content, ensure_ascii=False),
            }
        )

        # tool_result
        yield _make_sse(
            "tool_result",
            {
                "id": tc.tool_call_id,
                "name": tc.tool_name,
                "success": result.success,
                "summary": result.summary,
                "data": result.data,
            },
        )

    def _handle_confirm_tool(
        self,
        tc: PaperMindToolCall,
        conversation: list[dict],
    ) -> Iterator[str]:
        """处理需要确认的工具：存 pending → yield action_confirm → return"""
        action_id = f"act_{uuid4().hex[:12]}"
        logger.info(
            "确认操作挂起: %s [%s] args=%s",
            action_id,
            tc.tool_name,
            tc.arguments,
        )

        # 清理过期 actions
        self._confirm_mixin.cleanup_expired_actions()

        # 持久化到数据库
        self._confirm_mixin.store_pending_action(
            action_id=action_id,
            tool_name=tc.tool_name,
            tool_args=tc.arguments,
            tool_call_id=tc.tool_call_id,
            conversation_state={"conversation": conversation},
        )

        desc = self._confirm_mixin.describe_action(tc.tool_name, tc.arguments)
        yield _make_sse(
            "action_confirm",
            {
                "id": action_id,
                "tool": tc.tool_name,
                "args": tc.arguments,
                "description": desc,
            },
        )

    def _build_messages(self, conversation: list[dict]) -> list[dict]:
        """从 conversation 提取 OpenAI 格式的 messages"""
        # conversation 本身已经是 OpenAI 格式
        return conversation

    def _build_assistant_message(self, text_buf: str, tool_calls: list[PaperMindToolCall]) -> dict:
        return {
            "role": "assistant",
            "content": text_buf,
            "tool_calls": [
                {
                    "id": tc.tool_call_id,
                    "type": "function",
                    "function": {
                        "name": tc.tool_name,
                        "arguments": json.dumps(tc.arguments),
                    },
                }
                for tc in tool_calls
            ],
        }

    # -- 对外接口：confirm/reject 后继续循环 --
    def continue_after_confirmation(
        self,
        conversation: list[dict],
    ) -> Iterator[str]:
        """confirm/reject 后继续循环（从 conversation 恢复）"""
        yield from self.run(conversation)
        yield _make_sse("done", {})

    def execute_confirmed_action(
        self,
        action: dict,
        conversation: list[dict],
    ) -> Iterator[str]:
        """执行已确认的 action，继续循环"""
        tool_call_id = action["tool_call_id"]
        tool_name = action["tool"]
        args = action["args"]

        yield _make_sse(
            "tool_start",
            {
                "id": tool_call_id,
                "name": tool_name,
                "args": args,
            },
        )

        result = PaperMindToolResult(success=False, summary="无结果")
        for item in self.execute_fn(tool_name, args):
            if isinstance(item, PaperMindToolProgress):
                yield _make_sse(
                    "tool_progress",
                    {
                        "id": tool_call_id,
                        "message": item.message,
                        "current": item.current,
                        "total": item.total,
                    },
                )
            elif isinstance(item, PaperMindToolResult):
                result = item
            elif hasattr(item, "success") and hasattr(item, "data") and hasattr(item, "summary"):
                result = PaperMindToolResult(
                    success=item.success, data=item.data or {}, summary=item.summary
                )

        yield _make_sse(
            "action_result",
            {
                "id": action.get("action_id", ""),
                "success": result.success,
                "summary": result.summary,
                "data": result.data,
            },
        )

        # 注入 tool result 到 conversation
        conversation.append(
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps(
                    {
                        "success": result.success,
                        "summary": result.summary,
                        "data": result.data,
                    },
                    ensure_ascii=False,
                ),
            }
        )

        # 继续循环
        yield from self.run(conversation)
        yield _make_sse("done", {})

    def execute_rejected_action(
        self,
        action: dict,
        conversation: list[dict],
    ) -> Iterator[str]:
        """注入拒绝信息，继续循环让 LLM 给替代建议"""
        tool_call_id = action["tool_call_id"]

        yield _make_sse(
            "action_result",
            {
                "id": action.get("action_id", ""),
                "success": False,
                "summary": "用户已取消该操作",
                "data": {},
            },
        )

        # 注入拒绝信息
        conversation.append(
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps(
                    {
                        "success": False,
                        "summary": "用户拒绝了此操作，请提供替代方案或询问用户意见",
                        "data": {},
                    },
                    ensure_ascii=False,
                ),
            }
        )

        yield from self.run(conversation)
        yield _make_sse("done", {})

    def execute_and_continue(
        self,
        action: dict,
        conversation: list[dict],
    ) -> Iterator[str]:
        """
        执行已确认的 action（来自 confirmed_action_id），继续循环。
        用于 stream_chat(messages, confirmed_action_id=xxx) 场景。
        """
        tool_call_id = action["tool_call_id"]
        tool_name = action["tool"]
        args = action["args"]

        yield _make_sse(
            "tool_start",
            {
                "id": tool_call_id,
                "name": tool_name,
                "args": args,
            },
        )

        result = PaperMindToolResult(success=False, summary="无结果")
        for item in self.execute_fn(tool_name, args):
            if isinstance(item, PaperMindToolProgress):
                yield _make_sse(
                    "tool_progress",
                    {
                        "id": tool_call_id,
                        "message": item.message,
                        "current": item.current,
                        "total": item.total,
                    },
                )
            elif isinstance(item, PaperMindToolResult):
                result = item
            elif hasattr(item, "success") and hasattr(item, "data") and hasattr(item, "summary"):
                result = PaperMindToolResult(
                    success=item.success, data=item.data or {}, summary=item.summary
                )

        yield _make_sse(
            "action_result",
            {
                "id": action.get("action_id", ""),
                "success": result.success,
                "summary": result.summary,
                "data": result.data,
            },
        )

        conversation.append(
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": json.dumps(
                    {
                        "success": result.success,
                        "summary": result.summary,
                        "data": result.data,
                    },
                    ensure_ascii=False,
                ),
            }
        )

        yield from self.run(conversation)
        yield _make_sse("done", {})
