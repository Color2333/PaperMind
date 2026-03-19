"""Agent 对话路由
@author Color2333
"""

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from packages.ai.agent_service import confirm_action, reject_action, stream_chat
from packages.domain.schemas import AgentChatRequest

router = APIRouter()

_SSE_HEADERS = {
    "Cache-Control": "no-cache, no-store",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
    "X-Content-Type-Options": "nosniff",
}


@router.post("/agent/chat")
async def agent_chat(req: AgentChatRequest):
    """Agent 对话 - SSE 流式响应（带持久化 + 工具调用记录）"""
    from packages.storage.db import session_scope
    from packages.storage.repositories import AgentConversationRepository, AgentMessageRepository

    # 追踪已保存的用户消息内容，避免重复保存
    saved_user_contents: set[str] = set()

    # 如果有 conversation_id，保存到该会话；否则创建新会话
    conversation_id = getattr(req, "conversation_id", None)
    with session_scope() as session:
        conv_repo = AgentConversationRepository(session)
        msg_repo = AgentMessageRepository(session)

        if conversation_id:
            conv = conv_repo.get_by_id(conversation_id)
            if not conv:
                conversation_id = None

        if not conversation_id:
            first_user_msg = next((m for m in req.messages if m.role == "user"), None)
            title = first_user_msg.content[:50] if first_user_msg else "新对话"
            conv = conv_repo.create(title=title)
            conversation_id = conv.id

        # 只保存最新一条用户消息（避免重复）
        # 找到最后一条用户消息
        latest_user_msg = None
        for msg in reversed(req.messages):
            if msg.role == "user":
                latest_user_msg = msg
                break

        if latest_user_msg:
            # 用内容的 hash 作为去重 key
            content_key = latest_user_msg.content[:200]
            if content_key not in saved_user_contents:
                msg_repo.create(
                    conversation_id=conversation_id,
                    role=latest_user_msg.role,
                    content=latest_user_msg.content,
                )
                saved_user_contents.add(content_key)
    # 流式响应
    msgs = [m.model_dump() for m in req.messages]

    def _save_assistant_response(content: str, tool_calls: list | None = None):
        """保存助手响应（包含工具调用）"""
        with session_scope() as session:
            msg_repo = AgentMessageRepository(session)
            meta = {"tool_calls": tool_calls} if tool_calls else None
            msg_repo.create(
                conversation_id=conversation_id,
                role="assistant",
                content=content,
                meta=meta,
            )

    # SSE 解析：提取文本和工具调用
    import json
    import re

    # 用于累积助手响应
    text_content = ""
    tool_calls_records: list[dict] = []

    # SSE 格式: "event: xxx\ndata: {...}\n\n"
    _sse_pattern = re.compile(r"^event:\s*(\S+)\ndata:\s*(.+?)\n\n", re.DOTALL)

    def _parse_sse_chunk(chunk: str) -> tuple[str | None, dict | None]:
        """解析 SSE chunk，返回 (event_type, data)"""
        match = _sse_pattern.match(chunk)
        if match:
            event_type = match.group(1)
            try:
                data = json.loads(match.group(2))
                return event_type, data
            except json.JSONDecodeError:
                pass
        return None, None

    def stream_with_save():
        nonlocal text_content, tool_calls_records
        for chunk in stream_chat(msgs, confirmed_action_id=req.confirmed_action_id):
            # 解析 SSE 事件
            event_type, data = _parse_sse_chunk(chunk)
            if event_type and data:
                if event_type == "text_delta":
                    # 累积文本内容
                    text_content += data.get("content", "")
                elif event_type == "tool_result":
                    # 记录工具调用结果
                    tool_calls_records.append(
                        {
                            "name": data.get("name"),
                            "success": data.get("success"),
                            "summary": data.get("summary"),
                            "data": data.get("data"),
                        }
                    )
                elif event_type == "action_result":
                    # 记录用户确认的操作结果
                    tool_calls_records.append(
                        {
                            "action_id": data.get("id"),
                            "success": data.get("success"),
                            "summary": data.get("summary"),
                            "data": data.get("data"),
                        }
                    )
            yield chunk

        # 流结束后保存助手响应
        if text_content or tool_calls_records:
            _save_assistant_response(
                text_content, tool_calls_records if tool_calls_records else None
            )

    return StreamingResponse(
        stream_with_save(),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.post("/agent/confirm/{action_id}")
async def agent_confirm(action_id: str):
    """确认执行 Agent 挂起的操作"""
    return StreamingResponse(
        confirm_action(action_id),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.post("/agent/reject/{action_id}")
async def agent_reject(action_id: str):
    """拒绝 Agent 挂起的操作"""
    return StreamingResponse(
        reject_action(action_id),
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
    from packages.storage.repositories import AgentConversationRepository, AgentMessageRepository

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
