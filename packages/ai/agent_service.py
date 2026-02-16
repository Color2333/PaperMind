"""
Agent 核心服务 - 对话管理、工具调度、确认流程
@author Bamzc
"""
from __future__ import annotations

import json
import logging
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
你是 PaperMind AI Agent，一个专业的学术论文研究助手。

## 核心能力

你可以调用多种工具来完成研究任务。对于不同类型的用户需求，请遵循以下策略：

### 知识问答（最重要！）
当用户提出**概念性、知识性问题**时（如"什么是 attention mechanism"、\
"NeRF 有哪些变体"、"对比一下 GAN 和 Diffusion Model"），**必须第一时间\
调用 ask_knowledge_base 工具**进行 RAG 检索回答。这是你最核心的能力。
- 不要自己编造答案，必须基于知识库中的论文内容回答
- 回答后引用来源论文 ID，让用户知道依据
- 如果知识库中没有相关内容，告知用户并建议从 arXiv 下载相关论文

### 搜索调研
用户要求搜索特定领域时，先用 search_papers 搜本地库，无结果则建议 ingest_arxiv。

### 论文获取与分析
从 arXiv 下载（ingest_arxiv）→ 粗读（skim_paper）→ 精读（deep_read_paper）\
→ 嵌入（embed_paper），按需组合。

### Wiki 和简报
generate_wiki 生成主题/论文综述，generate_daily_brief 生成简报。

### 订阅管理
当 ingest_arxiv 返回结果中包含 `suggest_subscribe: true` 时，\
**必须**询问用户：「要将这个主题设为持续订阅吗？这样系统会每天自动搜集最新论文。」
- 用户同意 → 调用 manage_subscription(topic_name=..., enabled=true)
- 用户拒绝 → 不调用，保持仅搜集一次

## 工作流程

### 第一步：需求理解
快速理解用户意图，简短确认。

### 第二步：制定计划
列出将执行的步骤（编号列表），让用户心中有数。

### 第三步：逐步执行
按计划执行，每步完成后简短汇报并**立即推进**下一步。

### 第四步：总结
所有步骤完成后给出完整总结。

## 关键规则

1. **RAG 优先**：任何知识问答类问题，第一步就调用 ask_knowledge_base。
2. **主动推进**：每步完成后立即进入下一步，绝不等待用户催促。
3. **流式播报**：逐步输出文字，让用户实时看到进度。先输出一段说明文字，\
再调用工具，不要沉默直接调工具。
4. **结果描述**：用自然语言描述结果，不要只显示原始数据。
5. **智能建议**：搜索结果为空时主动建议下载。
6. **单步确认**：写操作一次只调用一个，确认后继续。
7. **中文回答**：始终使用中文。
8. **不重复操作**：相同工具和参数不要调用两次。
9. **简洁高效**：不要长篇大论解释工具是什么，直接执行。

## ⚠️ 严禁预测结果（极其重要！）

- **绝对禁止**在调用工具之前输出假设性的结果或完成描述！
- 错误示例：「好的，现在开始从 arXiv 下载...已成功拉取 20 篇论文...」\
然后才调用 ingest_arxiv。
- 正确示例：「正在搜索...」然后调用 search_papers，等返回结果后再描述。
- 调用需要确认的工具（如 ingest_arxiv）时，只输出一句简短说明如\
「需要从 arXiv 下载论文，请确认。」然后立即调用工具。\
不要输出任何关于结果的预测文字。
- 所有描述结果的文字，必须在工具返回结果之后再输出。
"""

_CONFIRM_TOOLS = {t.name for t in TOOL_REGISTRY if t.requires_confirm}

# 待确认操作（含对话上下文，用于恢复执行）
_pending_actions: dict[str, dict] = {}


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


def _build_messages(user_messages: list[dict]) -> list[dict]:
    """组装发送给 LLM 的 messages，插入 system prompt"""
    openai_msgs: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT}
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


def _llm_loop(
    conversation: list[dict],
    llm: LLMClient,
    tools: list[dict],
    max_rounds: int = 8,
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

            yield _make_sse("tool_start", {
                "id": tc.tool_call_id,
                "name": tc.tool_name,
                "args": args,
            })
            result = ToolResult(success=False, summary="无结果")
            for item in execute_tool_stream(tc.tool_name, args):
                if isinstance(item, ToolProgress):
                    yield _make_sse("tool_progress", {
                        "id": tc.tool_call_id,
                        "message": item.message,
                        "current": item.current,
                        "total": item.total,
                    })
                elif isinstance(item, ToolResult):
                    result = item
            yield _make_sse("tool_result", {
                "id": tc.tool_call_id,
                "name": tc.tool_name,
                "success": result.success,
                "summary": result.summary,
                "data": result.data,
            })
            conversation.append({
                "role": "tool",
                "tool_call_id": tc.tool_call_id,
                "content": json.dumps({
                    "success": result.success,
                    "summary": result.summary,
                    "data": result.data,
                }, ensure_ascii=False),
            })

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
            _pending_actions[action_id] = {
                "tool": tc.tool_name,
                "args": args,
                "tool_call_id": tc.tool_call_id,
                "conversation": conversation,
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
        action = _pending_actions.pop(confirmed_action_id, None)
        if not action:
            yield _make_sse(
                "error",
                {"message": f"操作 {confirmed_action_id} 已过期"},
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
    action = _pending_actions.pop(action_id, None)
    if not action:
        yield _make_sse(
            "error",
            {"message": f"操作 {action_id} 不存在或已过期"},
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
        "id": action_id,
        "success": result.success,
        "summary": result.summary,
        "data": result.data,
    })

    conversation = action.get("conversation", [])
    if conversation:
        conversation.append({
            "role": "tool",
            "tool_call_id": action["tool_call_id"],
            "content": json.dumps({
                "success": result.success,
                "summary": result.summary,
                "data": result.data,
            }, ensure_ascii=False),
        })
        llm = LLMClient()
        tools = get_openai_tools()
        yield from _llm_loop(conversation, llm, tools)

    yield _make_sse("done", {})


def reject_action(action_id: str) -> Iterator[str]:
    """拒绝挂起的操作并让 LLM 给出替代建议"""
    logger.info("用户拒绝操作: %s", action_id)
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
            f"从 arXiv 下载论文"
            f"（搜索: {a.get('query', '?')}，"
            f"最多 {a.get('max_results', 20)} 篇）"
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
