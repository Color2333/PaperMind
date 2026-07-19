"""Agent v2 路由：LangGraph 后端（PoC，与现有 /agent/chat 并行）。

复用 apps.api.routers.agent 的持久化辅助函数（_db_messages_to_openai /
_stream_with_save_for_action / _parse_sse_events / _resolve_conversation_id_from_action），
把 stream_chat/confirm_action/reject_action 换成 langgraph_agent.entry 的 v2 版本。

PoC：不合 main，拍板替换后再删老 agent.py。
@author Color2333
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

# 复用老 agent.py 的持久化辅助（避免重复实现）
from apps.api.routers.agent import (
    _SSE_HEADERS,
    _db_messages_to_openai,
    _new_messages_to_dicts,
    _parse_sse_events,
    _resolve_conversation_id_from_action,
    _stream_with_save_for_action,
)
from packages.domain.schemas import AgentChatRequest  # noqa: TC001  FastAPI 需运行时可见以解析 body
from packages.langgraph_agent.entry import confirm_v2, reject_v2, stream_chat_v2

router = APIRouter()


@router.post("/agent/v2/chat")
async def agent_chat_v2(req: AgentChatRequest):
    """Agent v2 对话 —— LangGraph 后端，SSE 协议与 /agent/chat 一致。

    后端真相源逻辑（修①②③）与 /agent/chat 完全一致：DB 拼 history +
    SSE 首事件 conversation_init + done 去重。仅 agent 内核换成 LangGraph。
    """
    from packages.agent_core.sse import make_sse
    from packages.storage.db import session_scope
    from packages.storage.repositories import (
        AgentConversationRepository,
        AgentMessageRepository,
    )

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

        # 保存本次新消息（与老路径一致）
        saved_keys: set[str] = set()
        for msg in req.messages:
            if msg.role == "system":
                continue
            content_key = f"{msg.role}:{msg.content[:200]}"
            if content_key not in saved_keys:
                msg_repo.create(
                    conversation_id=conversation_id,
                    role=msg.role,
                    content=msg.content,
                    meta=msg.meta,
                )
                saved_keys.add(content_key)

        # 从 DB 读全量历史重建 OpenAI messages（修②后端拼历史）
        db_msgs = msg_repo.list_by_conversation(conversation_id, limit=500)
        history_msgs = _db_messages_to_openai(db_msgs)

    # 合并 DB 历史 + 本次新增（去重）
    new_msgs = _new_messages_to_dicts(req.messages)
    history_keys = {f"{m.get('role')}:{(m.get('content') or '')[:200]}" for m in history_msgs}
    extra_new = [
        m
        for m in new_msgs
        if f"{m.get('role')}:{(m.get('content') or '')[:200]}" not in history_keys
    ]
    msgs = history_msgs + extra_new

    text_buf = ""
    tool_records: list[dict] = []
    tool_call_id: str | None = None
    saved_done = False

    def stream_with_save():
        nonlocal text_buf, tool_records, tool_call_id, saved_done
        # 修①：SSE 首事件返 conversation_id
        yield make_sse("conversation_init", {"conversation_id": conversation_id})

        sse_iter, _ = stream_chat_v2(
            msgs, conversation_id, confirmed_action_id=req.confirmed_action_id
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
                    import json

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
                elif event_type == "done" and not saved_done and (text_buf or tool_records):
                    saved_done = True
                    import json

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


@router.post("/agent/v2/confirm/{action_id}")
async def agent_confirm_v2(action_id: str):
    """确认挂起的操作（LangGraph 后端，复用持久化逻辑）"""
    conversation_id = _resolve_conversation_id_from_action(action_id)
    return StreamingResponse(
        _stream_with_save_for_action(
            conversation_id,
            lambda: confirm_v2(action_id, conversation_id),
        ),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.post("/agent/v2/reject/{action_id}")
async def agent_reject_v2(action_id: str):
    """拒绝挂起的操作（LangGraph 后端，复用持久化逻辑）"""
    conversation_id = _resolve_conversation_id_from_action(action_id)
    return StreamingResponse(
        _stream_with_save_for_action(
            conversation_id,
            lambda: reject_v2(action_id, conversation_id),
        ),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


__all__ = ["router"]
