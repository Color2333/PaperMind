"""
Agent 核心服务 - 对话管理、工具调度、确认流程
@author Bamzc
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Iterator
from uuid import uuid4

from packages.ai.agent_tools import (
    TOOL_REGISTRY,
    ToolProgress,
    ToolResult,
    execute_tool_stream,
    get_openai_tools,
)
from packages.integrations.llm_client import LLMClient, StreamEvent
from packages.storage.db import session_scope
from packages.storage.repositories import PromptTraceRepository

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

_CONFIRM_TOOLS = {t.name for t in TOOL_REGISTRY if t.requires_confirm}

# 待确认操作（含对话上下文，用于恢复执行）
_pending_actions: dict[str, dict] = {}
_pending_lock = threading.Lock()
_ACTION_TTL = 1800  # 30 分钟过期


def _cleanup_expired_actions():
    """清理过期的 pending actions"""
    cutoff = time.time() - _ACTION_TTL
    with _pending_lock:
        expired = [
            k for k, v in _pending_actions.items()
            if v.get("created_at", 0) < cutoff
        ]
        for k in expired:
            del _pending_actions[k]
        if expired:
            logger.info("清理 %d 个过期 pending_actions", len(expired))


def _record_agent_usage(
    provider: str, model: str,
    input_tokens: int, output_tokens: int,
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
        from packages.storage.repositories import PaperRepository, TopicRepository
        from packages.domain.enums import ReadStatus
        parts: list[str] = []

        with session_scope() as session:
            paper_repo = PaperRepository(session)
            topic_repo = TopicRepository(session)

            # 订阅主题
            topics = topic_repo.list_topics(enabled_only=True)
            if topics:
                topic_names = [t.name for t in topics[:8]]
                parts.append(f"关注领域：{', '.join(topic_names)}")

            # 精读过的论文
            deep_read = paper_repo.list_by_read_status(ReadStatus.deep_read, limit=5)
            if deep_read:
                titles = [p.title[:60] for p in deep_read]
                parts.append(f"最近精读：{'; '.join(titles)}")

            # 粗读过的论文数量
            skimmed = paper_repo.list_by_read_status(ReadStatus.skimmed, limit=200)
            unread = paper_repo.list_by_read_status(ReadStatus.unread, limit=200)
            parts.append(f"论文库状态：{len(deep_read)} 篇精读、{len(skimmed)} 篇粗读、{len(unread)} 篇未读")

        if parts:
            return "\n\n## 用户画像\n" + "\n".join(f"- {p}" for p in parts)
    except Exception as exc:
        logger.warning("Failed to build user profile: %s", exc)
    return ""


def _build_messages(user_messages: list[dict]) -> list[dict]:
    """组装发送给 LLM 的 messages，插入 system prompt + 用户画像"""
    profile = _build_user_profile()
    openai_msgs: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT + profile}
    ]
    for m in user_messages:
        role = m.get("role", "user")
        if role == "tool":
            openai_msgs.append({
                "role": "tool",
                "tool_call_id": m.get("tool_call_id", ""),
                "content": m.get("content", ""),
            })
        elif role == "assistant" and m.get("tool_calls"):
            openai_msgs.append({
                "role": "assistant",
                "content": m.get("content", "") or None,
                "tool_calls": m["tool_calls"],
            })
        else:
            openai_msgs.append({
                "role": role,
                "content": m.get("content", ""),
            })
    return openai_msgs


def _make_sse(event: str, data: dict) -> str:
    """格式化 SSE 事件"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def _execute_and_emit(
    tool_name: str, args: dict, tool_call_id: str,
    result_event: str = "tool_result",
    action_id: str | None = None,
) -> Iterator[tuple[str, ToolResult]]:
    """执行工具并生成 SSE 事件流，返回 (sse_str, result) 的迭代器。
    最后一个 yield 的第二个元素为最终的 ToolResult。"""
    yield _make_sse("tool_start", {
        "id": tool_call_id, "name": tool_name, "args": args,
    }), ToolResult(success=False, summary="")

    result = ToolResult(success=False, summary="无结果")
    for item in execute_tool_stream(tool_name, args):
        if isinstance(item, ToolProgress):
            yield _make_sse("tool_progress", {
                "id": tool_call_id,
                "message": item.message,
                "current": item.current,
                "total": item.total,
            }), result
        elif isinstance(item, ToolResult):
            result = item

    emit_data: dict = {
        "id": action_id or tool_call_id,
        "success": result.success,
        "summary": result.summary,
        "data": result.data,
    }
    if result_event == "tool_result":
        emit_data["name"] = tool_name
    yield _make_sse(result_event, emit_data), result


def _build_tool_message(result: ToolResult, tool_call_id: str) -> dict:
    """构建工具结果消息（含失败提示）"""
    tool_content: dict = {
        "success": result.success,
        "summary": result.summary,
        "data": result.data,
    }
    if not result.success:
        tool_content["error_hint"] = (
            "工具执行失败。请分析原因，告知用户，并建议替代方案。不要用相同参数重试。"
        )
    return {
        "role": "tool",
        "tool_call_id": tool_call_id,
        "content": json.dumps(tool_content, ensure_ascii=False),
    }


def _llm_loop(
    conversation: list[dict],
    llm: LLMClient,
    tools: list[dict],
    max_rounds: int = 12,
) -> Iterator[str]:
    """
    LLM 循环核心：流式调用 LLM，处理工具调用。
    只读工具自动执行，写操作暂停等确认。
    """
    for round_idx in range(max_rounds):
        openai_msgs = _build_messages(conversation)
        text_buf = ""
        tool_calls: list[StreamEvent] = []

        for event in llm.chat_stream(
            openai_msgs, tools=tools, max_tokens=4096
        ):
            if event.type == "text_delta":
                text_buf += event.content
                yield _make_sse(
                    "text_delta", {"content": event.content}
                )
            elif event.type == "tool_call":
                tool_calls.append(event)
            elif event.type == "usage":
                _record_agent_usage(
                    provider=llm.provider,
                    model=event.model,
                    input_tokens=event.input_tokens,
                    output_tokens=event.output_tokens,
                )
            elif event.type == "error":
                yield _make_sse(
                    "error", {"message": event.content}
                )
                return

        # 没有工具调用 → 对话结束
        if not tool_calls:
            break

        # 记录 assistant 回复（含 tool_calls）
        assistant_msg: dict = {
            "role": "assistant",
            "content": text_buf,
            "tool_calls": [
                {
                    "id": tc.tool_call_id,
                    "type": "function",
                    "function": {
                        "name": tc.tool_name,
                        "arguments": tc.tool_arguments,
                    },
                }
                for tc in tool_calls
            ],
        }
        conversation.append(assistant_msg)

        # 处理工具调用：优先检查确认类工具
        confirm_calls = [
            tc for tc in tool_calls
            if tc.tool_name in _CONFIRM_TOOLS
        ]
        auto_calls = [
            tc for tc in tool_calls
            if tc.tool_name not in _CONFIRM_TOOLS
        ]

        # 有需要确认的工具时，先处理自动工具，再暂停
        for tc in auto_calls:
            try:
                args = (
                    json.loads(tc.tool_arguments)
                    if tc.tool_arguments
                    else {}
                )
            except json.JSONDecodeError:
                args = {}

            result = ToolResult(success=False, summary="")
            for sse, r in _execute_and_emit(tc.tool_name, args, tc.tool_call_id):
                yield sse
                result = r
            conversation.append(_build_tool_message(result, tc.tool_call_id))

        if confirm_calls:
            # 一次只处理一个确认类工具
            tc = confirm_calls[0]
            try:
                args = (
                    json.loads(tc.tool_arguments)
                    if tc.tool_arguments
                    else {}
                )
            except json.JSONDecodeError:
                args = {}

            action_id = f"act_{uuid4().hex[:12]}"
            logger.info(
                "确认操作挂起: %s [%s] args=%s",
                action_id, tc.tool_name, args,
            )
            with _pending_lock:
                _cleanup_expired_actions()
                _pending_actions[action_id] = {
                    "tool": tc.tool_name,
                    "args": args,
                    "tool_call_id": tc.tool_call_id,
                    "conversation": conversation,
                    "created_at": time.time(),
                }
            desc = _describe_action(tc.tool_name, args)
            yield _make_sse("action_confirm", {
                "id": action_id,
                "tool": tc.tool_name,
                "args": args,
                "description": desc,
            })
            return

    yield _make_sse("done", {})


def stream_chat(
    messages: list[dict],
    confirmed_action_id: str | None = None,
) -> Iterator[str]:
    """
    Agent 主入口：接收消息列表，返回 SSE 事件流。
    """
    llm = LLMClient()
    tools = get_openai_tools()
    conversation = list(messages)

    # 处理确认操作
    if confirmed_action_id:
        with _pending_lock:
            action = _pending_actions.pop(confirmed_action_id, None)
        if not action:
            yield _make_sse(
                "error",
                {"message": "该操作已过期（可能因为服务重启或超时）。请重新描述您的需求，Agent 会重新发起操作。"},
            )
            yield _make_sse("done", {})
            return

        yield _make_sse("tool_start", {
            "id": action["tool_call_id"],
            "name": action["tool"],
            "args": action["args"],
        })
        result = ToolResult(success=False, summary="无结果")
        for item in execute_tool_stream(action["tool"], action["args"]):
            if isinstance(item, ToolProgress):
                yield _make_sse("tool_progress", {
                    "id": action["tool_call_id"],
                    "message": item.message,
                    "current": item.current,
                    "total": item.total,
                })
            elif isinstance(item, ToolResult):
                result = item
        yield _make_sse("action_result", {
            "id": confirmed_action_id,
            "success": result.success,
            "summary": result.summary,
            "data": result.data,
        })

        conversation = action.get("conversation", conversation)
        conversation.append({
            "role": "tool",
            "tool_call_id": action["tool_call_id"],
            "content": json.dumps({
                "success": result.success,
                "summary": result.summary,
                "data": result.data,
            }, ensure_ascii=False),
        })

        yield from _llm_loop(conversation, llm, tools)
        yield _make_sse("done", {})
        return

    # 正常对话
    yield from _llm_loop(conversation, llm, tools)
    yield _make_sse("done", {})


def confirm_action(action_id: str) -> Iterator[str]:
    """确认执行挂起的操作并继续对话"""
    logger.info("用户确认操作: %s", action_id)
    with _pending_lock:
        action = _pending_actions.pop(action_id, None)
    if not action:
        yield _make_sse(
            "error",
            {"message": "该操作已过期（可能因为服务重启或超时）。请重新描述您的需求，Agent 会重新发起操作。"},
        )
        yield _make_sse("done", {})
        return

    result = ToolResult(success=False, summary="")
    for sse, r in _execute_and_emit(
        action["tool"], action["args"], action["tool_call_id"],
        result_event="action_result", action_id=action_id,
    ):
        yield sse
        result = r

    conversation = action.get("conversation", [])
    if conversation:
        conversation.append(_build_tool_message(result, action["tool_call_id"]))
        llm = LLMClient()
        tools = get_openai_tools()
        yield from _llm_loop(conversation, llm, tools)

    yield _make_sse("done", {})


def reject_action(action_id: str) -> Iterator[str]:
    """拒绝挂起的操作并让 LLM 给出替代建议"""
    logger.info("用户拒绝操作: %s", action_id)
    with _pending_lock:
        action = _pending_actions.pop(action_id, None)
    yield _make_sse("action_result", {
        "id": action_id,
        "success": False,
        "summary": "用户已取消该操作",
        "data": {},
    })

    # 恢复对话，注入拒绝信息，让 LLM 给替代建议
    if action and action.get("conversation"):
        conversation = action["conversation"]
        conversation.append({
            "role": "tool",
            "tool_call_id": action["tool_call_id"],
            "content": json.dumps({
                "success": False,
                "summary": "用户拒绝了此操作，请提供替代方案或询问用户意见",
                "data": {},
            }, ensure_ascii=False),
        })
        llm = LLMClient()
        tools = get_openai_tools()
        yield from _llm_loop(conversation, llm, tools)

    yield _make_sse("done", {})


def _describe_action(tool_name: str, args: dict) -> str:
    """生成操作描述"""
    descriptions = {
        "ingest_arxiv": lambda a: (
            f"入库选中的 {len(a.get('arxiv_ids', []))} 篇论文"
            f"（来源: {a.get('query', '?')}）"
        ),
        "skim_paper": lambda a: (
            f"对论文 {a.get('paper_id', '?')[:8]}..."
            " 执行粗读分析"
        ),
        "deep_read_paper": lambda a: (
            f"对论文 {a.get('paper_id', '?')[:8]}..."
            " 执行精读分析"
        ),
        "embed_paper": lambda a: (
            f"对论文 {a.get('paper_id', '?')[:8]}..."
            " 执行向量化嵌入"
        ),
        "generate_wiki": lambda a: (
            f"生成 {a.get('type', '?')} 类型 Wiki"
            f"（{a.get('keyword_or_id', '?')}）"
        ),
        "generate_daily_brief": lambda _: "生成每日研究简报",
        "manage_subscription": lambda a: (
            f"{'启用' if a.get('enabled') else '关闭'}主题"
            f"「{a.get('topic_name', '?')}」的定时搜集"
        ),
    }
    fn = descriptions.get(tool_name)
    if fn:
        return fn(args)
    return f"执行 {tool_name}"
