"""
Agent 核心服务 - 对话管理、工具调度、确认流程
@author Color2333
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from packages.agent_core.loop import StreamingAgentLoop
from packages.ai.agent_tools import (
    TOOL_REGISTRY,
    execute_tool_stream,
    get_openai_tools,
)
from packages.integrations.llm_client import LLMClient
from packages.storage.db import session_scope
from packages.storage.repositories import AgentPendingActionRepository

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
你是 PaperMind AI Agent，一个专业的学术论文研究助手。你能调用工具完成搜索、\
下载、分析、生成等研究任务。始终使用中文。

## 工具选择决策树（按优先级）

收到用户消息后，按此顺序判断意图：

1. **知识问答**（"什么是X"、"对比X和Y"、"X有哪些方法"）
   → 直接调 ask_knowledge_base，不要编造答案
   → 知识库无内容时告知用户并建议下载

2. **搜索本地库**（"帮我找"、"搜索"、已有论文查询）
   → 调 search_papers
   → 无结果时自动切到 search_arxiv 搜 arXiv

3. **搜索并下载新论文**（"下载"、"收集"、"拉取"、"最新的XX论文"）
   → 调 search_arxiv 获取候选
   → **停下来**，等用户在前端界面勾选要入库的论文
   → 用户确认后调 ingest_arxiv(arxiv_ids=[用户选的])

4. **分析论文**（"粗读"、"精读"、"分析图表"）
   → 先确认目标论文 ID，再调对应工具

5. **生成内容**（"Wiki"、"综述"、"简报"）
   → 调 generate_wiki 或 generate_daily_brief

6. **订阅管理**（"订阅"、"定时"、"每天收集"）
   → 调 manage_subscription

7. **模糊描述**（用户没给具体关键词，如"3D重建相关的"）
   → 先调 suggest_keywords 获取关键词建议
   → 展示给用户选择后再搜索

## 完整工作流示例

**示例 A：用户说"帮我找最新的3D重建论文并总结"**
1. 输出：「正在搜索 arXiv...」→ 调 search_arxiv(query="3D reconstruction")
2. 结果返回后：列出候选论文，说「请在上方勾选要入库的论文」
3. 用户确认入库后：结果显示入库完成
4. 自动继续：调 ask_knowledge_base(question="3D重建最新论文总结") 基于新入库的论文回答
5. 最后总结

**示例 B：用户说"attention mechanism 是什么"**
1. 直接调 ask_knowledge_base(question="attention mechanism 是什么")
2. 用返回的 markdown 回答用户，引用论文来源

**示例 C：用户说"帮我分析这篇论文 xxx"**
1. 调 get_paper_detail(paper_id="xxx") 确认论文存在
2. 调 skim_paper(paper_id="xxx") 粗读
3. 汇报粗读结果，询问是否需要精读

## 核心规则

1. **先输出一句话再调工具**：如「正在搜索...」，不要沉默直接调。
2. **严禁预测结果**：工具返回之前不要编造结果。
   - ❌「已成功找到 20 篇论文」→ 然后才调工具
   - ✅「正在搜索...」→ 调工具 → 看到结果后再描述
3. **主动推进**：一步完成后立即进入下一步，不要等用户催促。
4. **每次只调一个写操作工具**（ingest/skim/deep_read/embed/wiki/brief），等确认后继续。
   只读工具（search/ask/get_detail/timeline/list_topics）可以连续调多个。
5. **不重复失败操作**：工具返回 success=false 时，分析 summary 中的原因，\
   告知用户并建议替代方案，不要用相同参数重试。
6. **参数修正后可重试**：如果失败原因是参数问题，修正后重试一次。
7. **结果描述要简洁**：用自然语言概括工具返回的关键信息，\
   不要重复输出工具已返回的完整数据。
8. **订阅建议**：ingest_arxiv 返回 suggest_subscribe=true 时，\
   询问用户是否要设为持续订阅。
9. **空结果处理**：搜索无结果时主动建议换关键词或从 arXiv 下载。
10. **简洁回答**：不要长篇解释工具用途，直接执行任务。
"""

_ACTION_TTL = 1800  # 30 分钟


def _make_sse(event: str, data: dict) -> str:
    """格式化 SSE 事件"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


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

            skimmed = paper_repo.list_by_read_status(ReadStatus.skimmed, limit=200)
            unread = paper_repo.list_by_read_status(ReadStatus.unread, limit=200)
            parts.append(
                f"论文库状态：{len(deep_read)} 篇精读、{len(skimmed)} 篇粗读、{len(unread)} 篇未读"
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
) -> Iterator[str]:
    """
    Agent 主入口：接收消息列表，返回 SSE 事件流。
    """
    _cleanup_expired_actions()
    conversation = _build_messages(messages)

    # 处理确认操作
    if confirmed_action_id:
        action = _load_pending_action(confirmed_action_id)
        if not action:
            yield _make_sse(
                "error",
                {
                    "message": "该操作已过期（可能因为服务重启或超时）。请重新描述您的需求，Agent 会重新发起操作。"
                },
            )
            yield _make_sse("done", {})
            return

        loop = _create_loop(conversation)
        yield from loop.execute_and_continue(action, conversation)
        return

    # 正常对话
    loop = _create_loop(conversation)
    yield from loop.run(conversation)
    yield _make_sse("done", {})


def confirm_action(action_id: str) -> Iterator[str]:
    """确认执行挂起的操作并继续对话"""
    logger.info("用户确认操作: %s", action_id)

    action = _load_pending_action(action_id)
    if not action:
        yield _make_sse(
            "error",
            {
                "message": "该操作已过期（可能因为服务重启或超时）。请重新描述您的需求，Agent 会重新发起操作。"
            },
        )
        yield _make_sse("done", {})
        return

    # 删除 pending action
    try:
        with session_scope() as session:
            repo = AgentPendingActionRepository(session)
            repo.delete(action_id)
    except Exception as exc:
        logger.warning("删除 pending_action 失败: %s", exc)

    conversation = action.get("conversation", [])
    loop = _create_loop(conversation)
    yield from loop.execute_confirmed_action(action, conversation)


def reject_action(action_id: str) -> Iterator[str]:
    """拒绝挂起的操作并让 LLM 给出替代建议"""
    logger.info("用户拒绝操作: %s", action_id)

    action = _load_pending_action(action_id)

    # 删除 pending action
    if action:
        try:
            with session_scope() as session:
                repo = AgentPendingActionRepository(session)
                repo.delete(action_id)
        except Exception as exc:
            logger.warning("删除 pending_action 失败: %s", exc)

    # 发送拒绝结果
    yield _make_sse(
        "action_result",
        {
            "id": action_id,
            "success": False,
            "summary": "用户已取消该操作",
            "data": {},
        },
    )

    if action and action.get("conversation"):
        conversation = action["conversation"]
        loop = _create_loop(conversation)
        yield from loop.execute_rejected_action(action, conversation)
    else:
        yield _make_sse("done", {})
