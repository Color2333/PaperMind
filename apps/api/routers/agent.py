"""Agent 对话路由
@author Color2333
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from packages.ai.agent_service import confirm_action, reject_action, stream_chat
from packages.domain.schemas import AgentChatRequest

if TYPE_CHECKING:
    from collections.abc import Callable

router = APIRouter()

_SSE_HEADERS = {
    "Cache-Control": "no-cache, no-store",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
    "X-Content-Type-Options": "nosniff",
}


def _parse_sse_events(chunk: str) -> list[tuple[str, dict]]:
    """解析 SSE chunk，返回 [(event_type, data), ...]"""
    events = []
    # 每个事件块以 "event: xxx\ndata: {...}\n\n" 格式
    event_pattern = re.compile(r"event:\s*(\S+)\s*\ndata:\s*(\{.*?\})\s*\n\n", re.DOTALL)
    for match in event_pattern.finditer(chunk):
        event_type = match.group(1)
        try:
            data = json.loads(match.group(2))
            events.append((event_type, data))
        except json.JSONDecodeError:
            pass
    return events


@router.post("/agent/chat")
async def agent_chat(req: AgentChatRequest):
    """Agent 对话 - SSE 流式响应（带持久化 + 工具调用记录）"""
    from packages.storage.db import session_scope
    from packages.storage.repositories import (
        AgentConversationRepository,
        AgentMessageRepository,
    )

    conversation_id = getattr(req, "conversation_id", None)

    with session_scope() as session:
        conv_repo = AgentConversationRepository(session)
        msg_repo = AgentMessageRepository(session)

        # 已有 conversation_id：验证存在
        if conversation_id:
            conv = conv_repo.get_by_id(conversation_id)
            if not conv:
                conversation_id = None

        # 无 conversation_id：创建新会话
        if not conversation_id:
            first_user_msg = next((m for m in req.messages if m.role == "user"), None)
            title = first_user_msg.content[:50] if first_user_msg else "新对话"
            conv = conv_repo.create(title=title)
            conversation_id = conv.id

        # 保存本次请求带来的所有新消息（user + assistant + tool）
        # 已有的历史消息从 DB 加载，不重复保存
        saved_ids: set[str] = set()
        for msg in req.messages:
            if msg.role == "system":
                continue
            content_key = f"{msg.role}:{msg.content[:200]}"
            if content_key not in saved_ids:
                msg_repo.create(
                    conversation_id=conversation_id,
                    role=msg.role,
                    content=msg.content,
                    meta=msg.meta,
                )
                saved_ids.add(content_key)

    # 构建传给 stream_chat 的 messages（包含 DB 加载的历史）
    # 前端传的是本次新增消息，需要拼上 DB 里的历史
    msgs = [m.model_dump() for m in req.messages]

    def _build_save_callback(conv_id: str) -> Callable[[list[dict]], None]:
        """创建压缩回写回调"""

        def on_compact(compressed_messages: list[dict]):
            with session_scope() as session:
                msg_repo = AgentMessageRepository(session)
                # 删除旧消息，写入压缩后的消息
                msg_repo.delete_by_conversation(conv_id)
                for msg in compressed_messages:
                    msg_repo.create(
                        conversation_id=conv_id,
                        role=msg.get("role", "user"),
                        content=msg.get("content", ""),
                        meta=msg.get("meta"),
                    )

        return on_compact

    text_buf = ""
    tool_records: list[dict] = []
    tool_call_id: str | None = None

    def stream_with_save():
        nonlocal text_buf, tool_records, tool_call_id
        sse_iter, updated_conversation = stream_chat(
            msgs, confirmed_action_id=req.confirmed_action_id
        )
        for chunk in sse_iter:
            yield chunk

            for event_type, data in _parse_sse_events(chunk):
                if event_type == "text_delta":
                    text_buf += data.get("content", "")
                elif event_type == "tool_start":
                    tool_call_id = data.get("id")
                elif event_type == "tool_result":
                    tool_records.append(
                        {
                            "name": data.get("name"),
                            "success": data.get("success"),
                            "summary": data.get("summary"),
                            "data": data.get("data"),
                        }
                    )
                    # 立即保存 tool 消息到 DB
                    with session_scope() as session:
                        msg_repo = AgentMessageRepository(session)
                        msg_repo.create(
                            conversation_id=conversation_id,
                            role="tool",
                            content=json.dumps(
                                {
                                    "name": data.get("name"),
                                    "success": data.get("success"),
                                    "summary": data.get("summary"),
                                    "data": data.get("data"),
                                },
                                ensure_ascii=False,
                            ),
                            meta={"tool_call_id": tool_call_id},
                        )
                elif event_type == "action_result":
                    tool_records.append(
                        {
                            "action_id": data.get("id"),
                            "success": data.get("success"),
                            "summary": data.get("summary"),
                            "data": data.get("data"),
                        }
                    )
                elif event_type == "done" and (text_buf or tool_records):
                    with session_scope() as session:
                        msg_repo = AgentMessageRepository(session)
                        msg_repo.create(
                            conversation_id=conversation_id,
                            role="assistant",
                            content=text_buf,
                            meta={"tool_calls": tool_records} if tool_records else None,
                        )

    return StreamingResponse(
        stream_with_save(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.post("/agent/confirm/{action_id}")
async def agent_confirm(action_id: str):
    """确认执行 Agent 挂起的操作"""
    sse_iter, _ = confirm_action(action_id)
    return StreamingResponse(
        sse_iter,
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.post("/agent/reject/{action_id}")
async def agent_reject(action_id: str):
    """拒绝 Agent 挂起的操作"""
    sse_iter, _ = reject_action(action_id)
    return StreamingResponse(
        sse_iter,
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.get("/agent/conversations")
def list_conversations(limit: int = Query(default=50, ge=1, le=200)) -> dict:
    """获取所有对话会话列表"""
    from packages.storage.db import session_scope
    from packages.storage.repositories import AgentConversationRepository

    with session_scope() as session:
        repo = AgentConversationRepository(session)
        conversations = repo.list_all(limit=limit)
        return {
            "conversations": [
                {
                    "id": c.id,
                    "title": c.title or "无标题",
                    "created_at": c.created_at.isoformat(),
                    "updated_at": c.updated_at.isoformat(),
                }
                for c in conversations
            ]
        }


@router.get("/agent/conversations/{conversation_id}")
def get_conversation_messages(
    conversation_id: str, limit: int = Query(default=100, ge=1, le=500)
) -> dict:
    """获取指定会话的所有消息"""
    from packages.storage.db import session_scope
    from packages.storage.repositories import (
        AgentConversationRepository,
        AgentMessageRepository,
    )

    with session_scope() as session:
        conv_repo = AgentConversationRepository(session)
        msg_repo = AgentMessageRepository(session)

        conv = conv_repo.get_by_id(conversation_id)
        if not conv:
            raise HTTPException(status_code=404, detail="会话不存在")

        messages = msg_repo.list_by_conversation(conversation_id, limit=limit)
        return {
            "conversation": {
                "id": conv.id,
                "title": conv.title or "无标题",
                "created_at": conv.created_at.isoformat(),
            },
            "messages": [
                {
                    "id": m.id,
                    "role": m.role,
                    "content": m.content,
                    "meta": m.meta,
                    "created_at": m.created_at.isoformat(),
                }
                for m in messages
            ],
        }


@router.delete("/agent/conversations/{conversation_id}")
def delete_conversation(conversation_id: str) -> dict:
    """删除指定会话"""
    from packages.storage.db import session_scope
    from packages.storage.repositories import AgentConversationRepository

    with session_scope() as session:
        repo = AgentConversationRepository(session)
        deleted = repo.delete(conversation_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="会话不存在")
        return {"deleted": conversation_id}
