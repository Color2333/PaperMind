"""
Agent 核心服务 - 对话管理、工具调度、确认流程
@author Color2333
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from packages.agent_core.context_compaction import (
    CompactingStreamingAgentLoop,
    CompactionConfig,
    ContextCompactor,
)
from packages.agent_core.loop import StreamingAgentLoop
from packages.agent_core.sse import make_sse
from packages.agent_core.subagents import SubagentPool, SubagentRunner, get_subagent_pool
from packages.agent_core.todos import PlannerMixin, TodoManager, get_todo_manager
from packages.ai.agent_tools import (
    TOOL_REGISTRY,
    execute_tool_stream,
    get_openai_tools,
)
from packages.ai.prompts import SYSTEM_PROMPT
from packages.integrations.llm_client import LLMClient
from packages.storage.db import session_scope
from packages.storage.repositories import AgentPendingActionRepository

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

_ACTION_TTL = 1800  # 30 分钟

# 已处理（确认/拒绝）过的 action_id → 时间戳；用于幂等保护，避免重复 confirm 报"已过期"
_HANDLED_ACTION_CACHE: dict[str, float] = {}
_HANDLED_ACTION_TTL = 3600.0  # 1 小时


def _mark_action_handled(action_id: str) -> None:
    """标记 action 已被处理过（确认/拒绝），避免重复触发时报'已过期'"""
    _HANDLED_ACTION_CACHE[action_id] = time.time()
    # 控制缓存膨胀
    if len(_HANDLED_ACTION_CACHE) > 256:
        now = time.time()
        expired = [
            aid for aid, ts in _HANDLED_ACTION_CACHE.items() if now - ts > _HANDLED_ACTION_TTL
        ]
        for aid in expired:
            _HANDLED_ACTION_CACHE.pop(aid, None)


def _is_action_handled(action_id: str) -> bool:
    """判断 action 是否已被处理过（幂等保护）"""
    ts = _HANDLED_ACTION_CACHE.get(action_id)
    if ts is None:
        return False
    if time.time() - ts > _HANDLED_ACTION_TTL:
        _HANDLED_ACTION_CACHE.pop(action_id, None)
        return False
    return True


def _record_agent_usage(
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> None:
    """将 Agent 对话的 token 消耗写入 PromptTrace"""
    if not (input_tokens or output_tokens):
        return
    try:
        llm = LLMClient()
        in_cost, out_cost = llm._estimate_cost(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        with session_scope() as session:
            from packages.storage.repositories import PromptTraceRepository

            PromptTraceRepository(session).create(
                stage="agent_chat",
                provider=provider,
                model=model,
                prompt_digest="[agent streaming chat]",
                paper_id=None,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                input_cost_usd=in_cost,
                output_cost_usd=out_cost,
                total_cost_usd=in_cost + out_cost,
            )
    except Exception as exc:
        logger.warning("Failed to record agent usage: %s", exc)


def _build_user_profile() -> str:
    """从数据库提取用户画像：阅读历史、关注领域、最近活动"""
    try:
        from packages.domain.enums import ReadStatus
        from packages.storage.repositories import PaperRepository, TopicRepository

        parts: list[str] = []

        with session_scope() as session:
            paper_repo = PaperRepository(session)
            topic_repo = TopicRepository(session)

            topics = topic_repo.list_topics(enabled_only=True)
            if topics:
                topic_names = [t.name for t in topics[:8]]
                parts.append(f"关注领域：{', '.join(topic_names)}")

            deep_read = paper_repo.list_by_read_status(ReadStatus.deep_read, limit=5)
            if deep_read:
                titles = [p.title[:60] for p in deep_read]
                parts.append(f"最近精读：{'; '.join(titles)}")

            # 修⑭：此前用 limit 列表的 len 当总数（limit=5 → 精读永远≤5，真实 366）。
            # 改用 count_by_read_status 查真实总数
            deep_count = paper_repo.count_by_read_status(ReadStatus.deep_read)
            skim_count = paper_repo.count_by_read_status(ReadStatus.skimmed)
            unread_count = paper_repo.count_by_read_status(ReadStatus.unread)
            parts.append(
                f"论文库状态：{deep_count} 篇精读、{skim_count} 篇粗读、{unread_count} 篇未读"
            )

        if parts:
            return "\n\n## 用户画像\n" + "\n".join(f"- {p}" for p in parts)
    except Exception as exc:
        logger.warning("Failed to build user profile: %s", exc)
    return ""


def _build_messages(user_messages: list[dict]) -> list[dict]:
    """组装发送给 LLM 的 messages，插入 system prompt + 用户画像"""
    profile = _build_user_profile()
    openai_msgs: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT + profile}]
    for m in user_messages:
        role = m.get("role", "user")
        if role == "tool":
            openai_msgs.append(
                {
                    "role": "tool",
                    "tool_call_id": m.get("tool_call_id", ""),
                    "content": m.get("content", ""),
                }
            )
        elif role == "assistant" and m.get("tool_calls"):
            openai_msgs.append(
                {
                    "role": "assistant",
                    "content": m.get("content", "") or None,
                    "tool_calls": m["tool_calls"],
                }
            )
        else:
            openai_msgs.append(
                {
                    "role": role,
                    "content": m.get("content", ""),
                }
            )
    return openai_msgs


def _cleanup_expired_actions() -> None:
    """清理过期的 pending actions（数据库）"""
    try:
        with session_scope() as session:
            repo = AgentPendingActionRepository(session)
            deleted = repo.cleanup_expired(_ACTION_TTL)
            if deleted > 0:
                logger.info("清理 %d 个过期 pending_actions", deleted)
    except Exception as exc:
        logger.warning("清理过期 pending_actions 失败: %s", exc)


def _load_pending_action(action_id: str) -> dict | None:
    """从数据库读取 pending action"""
    try:
        with session_scope() as session:
            repo = AgentPendingActionRepository(session)
            record = repo.get_by_id(action_id)
            if record:
                return {
                    "action_id": action_id,
                    "tool": record.tool_name,
                    "args": record.tool_args,
                    "tool_call_id": record.tool_call_id,
                    "conversation": (record.conversation_state or {}).get("conversation", []),
                }
    except Exception as exc:
        logger.warning("读取 pending_action 失败: %s", exc)
    return None


def _create_loop(
    conversation: list[dict],
) -> StreamingAgentLoop:
    """创建配置好的 StreamingAgentLoop 实例"""
    llm = LLMClient()
    tools = get_openai_tools()

    def on_usage(provider: str, model: str, input_tokens: int, output_tokens: int) -> None:
        _record_agent_usage(provider, model, input_tokens, output_tokens)

    loop = StreamingAgentLoop(
        llm=llm,
        tools=tools,
        tool_registry=TOOL_REGISTRY,
        execute_fn=execute_tool_stream,
        session_scope=session_scope,
        on_usage=on_usage,
    )
    return loop


def stream_chat(
    messages: list[dict],
    confirmed_action_id: str | None = None,
) -> tuple[Iterator[str], list[dict]]:
    """
    Agent 主入口：接收消息列表，返回 (SSE事件流, 更新后的conversation)。

    注意：返回的 conversation 已包含所有 tool 消息和 assistant 回复，
    可用于持久化或后续处理。
    """
    _cleanup_expired_actions()
    conversation = _build_messages(messages)

    # 处理确认操作
    if confirmed_action_id:
        action = _load_pending_action(confirmed_action_id)
        if not action:
            # 幂等保护：已处理过的 action 给中性提示，不再报"已过期"
            already_handled = _is_action_handled(confirmed_action_id)
            err_msg = (
                "该操作已处理过，请继续后续对话。"
                if already_handled
                else "该操作已过期（可能因为服务重启或超时）。请重新描述您的需求，Agent 会重新发起操作。"
            )

            def _err_iter():
                yield make_sse("error", {"message": err_msg})
                yield make_sse("done", {})

            return _err_iter(), conversation

        _mark_action_handled(confirmed_action_id)
        loop = _create_loop(conversation)

        def _confirm_iter():
            yield from loop.execute_and_continue(action, conversation)
            # 修④：loop 内部已发 done，service 不再重复 yield（此前导致 done=2~3 重复持久化）

        return _confirm_iter(), conversation

    # 正常对话
    loop = _create_loop(conversation)

    def _chat_iter():
        yield from loop.run(conversation)
        # 修④：loop 内部已发 done，service 不再重复

    return _chat_iter(), conversation


def confirm_action(action_id: str) -> tuple[Iterator[str], list[dict]]:
    """确认执行挂起的操作并继续对话"""
    logger.info("用户确认操作: %s", action_id)

    action = _load_pending_action(action_id)
    if not action:
        # 幂等保护：之前确认/拒绝过就明确提示，不再和"真过期"混淆
        already_handled = _is_action_handled(action_id)
        err_msg = (
            "该操作已处理过，请继续后续对话。"
            if already_handled
            else "该操作已过期（可能因为服务重启或超时）。请重新描述您的需求，Agent 会重新发起操作。"
        )

        def _err_iter():
            yield make_sse("error", {"message": err_msg})
            yield make_sse("done", {})

        return _err_iter(), []

    # 立即标记已处理，防止用户双击 / 网络重试导致二次执行
    _mark_action_handled(action_id)

    # 删除 pending action
    try:
        with session_scope() as session:
            repo = AgentPendingActionRepository(session)
            repo.delete(action_id)
    except Exception as exc:
        logger.warning("删除 pending_action 失败: %s", exc)

    conversation = action.get("conversation", [])
    loop = _create_loop(conversation)

    def _confirm_iter():
        yield from loop.execute_confirmed_action(action, conversation)
        # 修④：loop 内部已发 done，service 不再重复

    return _confirm_iter(), conversation


def reject_action(action_id: str) -> tuple[Iterator[str], list[dict]]:
    """拒绝挂起的操作并让 LLM 给出替代建议"""
    logger.info("用户拒绝操作: %s", action_id)

    action = _load_pending_action(action_id)

    # 标记已处理 + 删除 pending action
    if action:
        _mark_action_handled(action_id)
        try:
            with session_scope() as session:
                repo = AgentPendingActionRepository(session)
                repo.delete(action_id)
        except Exception as exc:
            logger.warning("删除 pending_action 失败: %s", exc)

    conversation = action.get("conversation", []) if action else []
    loop = _create_loop(conversation) if conversation else None

    def _reject_iter():
        yield make_sse(
            "action_result",
            {
                "id": action_id,
                "success": False,
                "summary": "用户已取消该操作",
                "data": {},
            },
        )
        if loop:
            yield from loop.execute_rejected_action(action, conversation)
        # 修④：loop 内部已发 done，service 不再重复

    return _reject_iter(), conversation


__all__ = [
    "stream_chat",
    "confirm_action",
    "reject_action",
    "CompactingStreamingAgentLoop",
    "ContextCompactor",
    "CompactionConfig",
    "TodoManager",
    "PlannerMixin",
    "get_todo_manager",
    "SubagentPool",
    "SubagentRunner",
    "get_subagent_pool",
]
