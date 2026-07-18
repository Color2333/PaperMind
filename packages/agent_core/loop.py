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
                                   │ llm.chat_stream()
                                   ▼
                         ┌─────────────────────┐
                         │       LLM           │
                         │ (OpenAI 兼容)       │
                         └──────────┬──────────┘
                                    │ stream events
                        有 tool_call 事件？
                                   │
                         ┌─────────┴─────────┐
                         │ yes               │ no
                         ▼                   ▼
               ┌─────────────────┐      ┌──────────┐
               │ for each call   │      │  return  │
               │ tool_call:      │      │  done    │
               │   execute()     │      └──────────┘
               │   append result │
               │ loop back ──────┼──→ conversation.append(result)
               └─────────────────┘
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from uuid import uuid4

if TYPE_CHECKING:
    from packages.integrations.llm_client import LLMClient, StreamEvent

from packages.agent_core.sse import make_sse

# -- Tool Definition (OpenAI function-calling format) --
ToolDef = dict[str, Any]
ToolHandler = Callable[..., str | dict[str, Any]]


# =============================================================================
# PaperMind 适配层：流式 Agent 循环 + 确认机制
# =============================================================================

logger = logging.getLogger(__name__)


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
                yield make_sse("done", {})
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
                # 修⑧：LLM 一轮内可能返回多个 confirm 工具，之前只处理 confirm_calls[0]
                # 其余被丢弃，导致 tool_calls 与 tool_result 不配对，下轮 LLM 报错。
                # 现处理首个（挂起），其余转文本提示让 LLM 下一轮重提。
                tc = confirm_calls[0]
                if len(confirm_calls) > 1:
                    extra = len(confirm_calls) - 1
                    for extra_tc in confirm_calls[1:]:
                        conversation.append(
                            {
                                "role": "tool",
                                "tool_call_id": extra_tc.tool_call_id,
                                "content": f"还有 {extra} 个待确认操作（{extra_tc.tool_name}），"
                                f"请先确认当前操作后再继续。",
                            }
                        )
                yield from self._handle_confirm_tool(tc, conversation)
                return

        # 修⑩：max_rounds 耗尽不应静默截断，给用户一个提示再 done
        yield make_sse(
            "text_delta",
            {"content": "\n\n[已达到本轮最大对话轮次，如有需要请继续提问]"},
        )
        yield make_sse("done", {})

    def _handle_stream_event(
        self,
        event: StreamEvent,
        text_buf: str,
        tool_calls: list[PaperMindToolCall],
    ) -> str | None:
        """处理单个流事件，返回 SSE 字符串或 None"""
        if event.type == "text_delta":
            return make_sse("text_delta", {"content": event.content})
        elif event.type == "tool_call":
            # 修⑨：tool_arguments 非法 JSON 时不应崩整个 run，跳过该 tool_call + 报错
            args: dict = {}
            if event.tool_arguments:
                try:
                    args = json.loads(event.tool_arguments)
                    if not isinstance(args, dict):
                        args = {}
                except (json.JSONDecodeError, TypeError) as e:
                    logger.warning(
                        "tool_call 参数 JSON 解析失败，跳过: %s [%s] err=%s",
                        event.tool_call_id,
                        event.tool_name,
                        e,
                    )
                    return make_sse(
                        "error",
                        {"message": f"工具 {event.tool_name} 参数解析失败，已跳过"},
                    )
            tool_calls.append(
                PaperMindToolCall(
                    tool_call_id=event.tool_call_id,
                    tool_name=event.tool_name,
                    arguments=args,
                )
            )
        elif event.type == "error":
            return make_sse("error", {"message": event.content})
        elif event.type == "usage" and self._on_usage:
            # 修⑬：provider 应从 llm 取真实 provider，model 从 event 取；之前两个参数都传 event.model
            self._on_usage(
                self.llm.provider or "",
                event.model or "",
                event.input_tokens or 0,
                event.output_tokens or 0,
            )
        return None

    def _iterate_tool(
        self,
        tool_name: str,
        args: dict,
        tool_call_id: str,
        result_holder: list[PaperMindToolResult],
    ) -> Iterator[str]:
        """执行工具的公共逻辑：发 tool_start → 流式执行 → 累积 result 到 holder[0]

        各调用方负责发自己的 result 类 SSE 事件（tool_result / action_result）
        和 conversation append，以保留各自不同的外围脚手架。
        """
        yield make_sse(
            "tool_start",
            {"id": tool_call_id, "name": tool_name, "args": args},
        )

        result = PaperMindToolResult(success=False, summary="无结果")
        for item in self.execute_fn(tool_name, args):
            if isinstance(item, PaperMindToolProgress):
                yield make_sse(
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
                # agent_tools.ToolResult（不同模块的同名类）
                result = PaperMindToolResult(
                    success=item.success, data=item.data or {}, summary=item.summary
                )
        result_holder.clear()
        result_holder.append(result)

    def _execute_and_emit(
        self,
        tc: PaperMindToolCall,
        conversation: list[dict],
    ) -> Iterator[str]:
        """执行工具并 yield SSE 事件"""
        holder: list[PaperMindToolResult] = []
        yield from self._iterate_tool(tc.tool_name, tc.arguments, tc.tool_call_id, holder)
        result = holder[0]

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
        yield make_sse(
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
        yield make_sse(
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
        yield make_sse("done", {})

    def execute_confirmed_action(
        self,
        action: dict,
        conversation: list[dict],
    ) -> Iterator[str]:
        """执行已确认的 action，继续循环"""
        tool_call_id = action["tool_call_id"]
        tool_name = action["tool"]
        args = action["args"]

        holder: list[PaperMindToolResult] = []
        yield from self._iterate_tool(tool_name, args, tool_call_id, holder)
        result = holder[0]

        yield make_sse(
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
        yield make_sse("done", {})

    def execute_rejected_action(
        self,
        action: dict,
        conversation: list[dict],
    ) -> Iterator[str]:
        """注入拒绝信息，继续循环让 LLM 给替代建议"""
        tool_call_id = action["tool_call_id"]

        yield make_sse(
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
        yield make_sse("done", {})

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

        holder: list[PaperMindToolResult] = []
        yield from self._iterate_tool(tool_name, args, tool_call_id, holder)
        result = holder[0]

        yield make_sse(
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
        yield make_sse("done", {})
