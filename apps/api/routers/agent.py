"""Agent 对话路由

引擎双轨（设计④：Pi 是 agent 循环 + LLM 网关的唯一实现）：
- pi（默认）：packages.agent_pi 桥 spawn `pm -p --json`，多轮上下文由
  Pi session 文件承载；LLM 配置从 DB 物化，pm 工具经用户 JWT 回访 API；
- python（回退）：packages.ai.agent_service 原生引擎（确认操作机制仅在
  此引擎可用——Pi 工具为服务端受控白名单，无需前端二次确认）。

引擎经 SSE `engine` 事件通告前端（徽标展示）；pm 不可用时自动回退 python。

@author Color2333
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable  # noqa: TC003  FastAPI 需运行时可见以解析 body 注解

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from packages.agent_core.sse import make_sse
from packages.ai.agent_service import confirm_action, reject_action, stream_chat
from packages.domain.schemas import (
    AgentChatRequest,  # noqa: TC001  FastAPI 需运行时可见以解析 body 注解
)

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


def _db_messages_to_openai(db_messages: list) -> list[dict]:
    """把 DB 中的 AgentMessage 重建为 OpenAI 格式 messages。

    - assistant + meta.tool_calls → {role, content, tool_calls}
    - tool + meta.tool_call_id → {role, tool_call_id, content}
    - 其余 → {role, content}

    修②：后端真相源要求后端拼历史，不再依赖前端重发全历史。
    """
    openai_msgs: list[dict] = []
    for m in db_messages:
        role = m.role
        meta = m.meta or {}
        if role == "assistant" and meta.get("tool_calls"):
            openai_msgs.append(
                {
                    "role": "assistant",
                    "content": m.content or None,
                    "tool_calls": meta["tool_calls"],
                }
            )
        elif role == "tool":
            openai_msgs.append(
                {
                    "role": "tool",
                    "tool_call_id": meta.get("tool_call_id", ""),
                    "content": m.content,
                }
            )
        else:
            openai_msgs.append({"role": role, "content": m.content})
    return openai_msgs


def _new_messages_to_dicts(req_messages: list) -> list[dict]:
    """把本次请求带来的新消息（AgentMessage schema）转成 OpenAI dict。

    前端修③后只发本次新增 user 消息，但兼容前端仍发 assistant/tool 的情况。
    """
    out: list[dict] = []
    for m in req_messages:
        role = m.role
        if role == "assistant" and (m.meta or {}).get("tool_calls"):
            out.append(
                {
                    "role": "assistant",
                    "content": m.content or None,
                    "tool_calls": m.meta["tool_calls"],
                }
            )
        elif role == "tool":
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": (m.meta or {}).get("tool_call_id", "") or m.tool_call_id or "",
                    "content": m.content,
                }
            )
        else:
            out.append({"role": role, "content": m.content})
    return out


def _select_engine(confirmed_action_id: str | None) -> str:
    """引擎选择：确认操作机制仅 Python 引擎实现 → 强制回退；
    其余按 PAPERMIND_AGENT_ENGINE（默认 pi），pm 不可用再降级。"""
    forced = os.environ.get("PAPERMIND_AGENT_ENGINE", "pi").strip().lower()
    if confirmed_action_id or forced == "python":
        return "python"
    return "pi"


@router.get("/agent/engine")
def agent_engine() -> dict:
    """当前聊天引擎状态（Settings LLM Gateway / 聊天页徽标数据源）。

    - engine：本次会话实际使用的引擎（pi=Pi agent core / python=回退）；
    - pm_available：pm 二进制是否就位（False 时 pi 自动降级 python）；
    - chat_model：Pi 聊天模型（DB active 配置的 model_skim）。
    """
    from packages.agent_pi import pi_engine_available
    from packages.agent_pi.host import _get_active_llm_config

    pm_ok = pi_engine_available()
    forced = os.environ.get("PAPERMIND_AGENT_ENGINE", "pi").strip().lower()
    engine = "python" if (not pm_ok or forced == "python") else "pi"
    cfg = _get_active_llm_config() or {}
    return {
        "engine": engine,
        "pm_available": pm_ok,
        "forced": forced,
        "chat_model": cfg.get("model_skim"),
        "provider": cfg.get("provider"),
    }


@router.post("/agent/chat")
async def agent_chat(req: AgentChatRequest, request: Request):
    """Agent 对话 - SSE 流式响应（带持久化 + 工具调用记录）

    修②：后端真相源——前端只发本次新增消息，后端按 conversation_id 从 DB
    读历史拼接。新会话首条消息后端创建并经 SSE 返 conversation_id（修①）。
    """
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

        # 无 conversation_id：创建新会话（先建空壳，首条 user 消息稍后存）
        if not conversation_id:
            first_user_msg = next((m for m in req.messages if m.role == "user"), None)
            title = first_user_msg.content[:50] if first_user_msg else "新对话"
            conv = conv_repo.create(title=title)
            conversation_id = conv.id

        # 保存本次请求带来的所有新消息（user + assistant + tool）
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

        # 修②：从 DB 读全量历史，重建为 OpenAI 格式，作为传给 stream_chat 的 messages
        db_msgs = msg_repo.list_by_conversation(conversation_id, limit=500)
        history_msgs = _db_messages_to_openai(db_msgs)

    # 构建传给 stream_chat 的 messages：DB 历史 + 本次新增（前端只发新增时，req.messages 即新增）
    # 已在 DB 中存的本次新增消息，list_by_conversation 也会读出，避免重复加入。
    new_msgs = _new_messages_to_dicts(req.messages)
    # 用 content key 去重：DB 历史已含本次新增，只需把 DB 没覆盖到的情况补齐
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
    saved_done = False  # 修④：done 去重，一个 stream 只存一次 assistant

    engine = _select_engine(req.confirmed_action_id)
    if engine == "pi":
        from packages.agent_pi import pi_engine_available

        if not pi_engine_available():
            engine = "python"  # pm 未部署：透明回退，前端经 engine 事件知情

    def sse_iter_factory():
        """按引擎产出 SSE 流（统一契约，持久化循环共用）。"""
        if engine == "python":
            return stream_chat(msgs, confirmed_action_id=req.confirmed_action_id)[0]
        from packages.agent_pi import pi_chat_stream

        last_user = next((m.content for m in reversed(req.messages) if m.role == "user"), None)
        if not last_user:

            def _empty():
                yield make_sse("error", {"message": "缺少用户消息"})
                yield make_sse("done", {})

            return _empty()
        return pi_chat_stream(
            conversation_id, last_user, auth_header=request.headers.get("Authorization")
        )

    def stream_with_save():
        nonlocal text_buf, tool_records, tool_call_id, saved_done
        # 修①：SSE 首事件返 conversation_id，前端采用后端 id 作 localStorage key
        yield make_sse("conversation_init", {"conversation_id": conversation_id})
        yield make_sse("engine", {"engine": engine})

        for chunk in sse_iter_factory():
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
                elif event_type == "done" and not saved_done and (text_buf or tool_records):
                    # 修④：只存一次 assistant，后续 done（loop 内部/重试）跳过
                    saved_done = True
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


def _resolve_conversation_id_from_action(action_id: str) -> str | None:
    """从 pending action 取 conversation_id，供 confirm/reject 持久化用。"""
    from packages.storage.db import session_scope
    from packages.storage.repositories import AgentPendingActionRepository

    try:
        with session_scope() as session:
            repo = AgentPendingActionRepository(session)
            record = repo.get_by_id(action_id)
            return record.conversation_id if record else None
    except Exception:
        return None


def _stream_with_save_for_action(
    conversation_id: str | None,
    sse_iter_factory: Callable[[], tuple],
):
    """修⑤：confirm/reject 复用同样的持久化逻辑。

    sse_iter_factory 返回 (sse_iter, conversation)。
    """
    text_buf = ""
    tool_records: list[dict] = []
    tool_call_id: str | None = None
    saved_done = False

    def _gen():
        nonlocal text_buf, tool_records, tool_call_id, saved_done
        from packages.storage.db import session_scope
        from packages.storage.repositories import AgentMessageRepository

        if conversation_id:
            yield make_sse("conversation_init", {"conversation_id": conversation_id})

        sse_iter, _conversation = sse_iter_factory()
        for chunk in sse_iter:
            yield chunk
            if not conversation_id:
                continue
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
                    with session_scope() as session:
                        msg_repo = AgentMessageRepository(session)
                        msg_repo.create(
                            conversation_id=conversation_id,
                            role="assistant",
                            content=text_buf,
                            meta={"tool_calls": tool_records} if tool_records else None,
                        )

    return _gen()


@router.post("/agent/pending-actions")
def create_pending_action(body: dict):
    """Pi 工具（pm 子进程，持用户 JWT）创建破坏性操作确认请求。

    E7：webchat headless 无本地确认 UI——工具建 pending-action 后轮询本
    端点族的决定；决定落在 conversation_state JSON（免 schema 迁移）。
    """
    from uuid import uuid4

    from packages.storage.db import session_scope
    from packages.storage.repositories import AgentPendingActionRepository

    tool = str(body.get("tool") or "").strip()
    if not tool:
        raise HTTPException(status_code=400, detail="tool required")
    with session_scope() as session:
        record = AgentPendingActionRepository(session).create(
            action_id=str(uuid4()),
            tool_name=tool,
            tool_args=body.get("args") if isinstance(body.get("args"), dict) else {},
            conversation_id=body.get("conversation_id"),
            conversation_state={
                "engine": "pi",
                "status": "pending",
                "description": str(body.get("description") or ""),
            },
        )
        return {"id": record.id, "status": "pending"}


@router.get("/agent/pending-actions/{action_id}")
def get_pending_action(action_id: str):
    """Pi 工具轮询确认决定（pending/approved/rejected）；不存在=已过期。"""
    from packages.storage.db import session_scope
    from packages.storage.repositories import AgentPendingActionRepository

    with session_scope() as session:
        record = AgentPendingActionRepository(session).get_by_id(action_id)
        if record is None:
            raise HTTPException(status_code=404, detail="确认请求不存在或已过期")
        state = record.conversation_state or {}
        return {
            "id": record.id,
            "status": state.get("status", "pending"),
            "tool": record.tool_name,
            "description": state.get("description") or "",
        }


def _resolve_pi_action(action_id: str, decision: str) -> bool:
    """若该 action 属于 Pi 引擎：持久落决定并返回 True（不走 Python 引擎的
    "流暂停-续播" SSE——Pi 工具在原 SSE 流内轮询到此决定后自行继续/取消）。"""
    from packages.storage.db import session_scope
    from packages.storage.repositories import AgentPendingActionRepository

    with session_scope() as session:
        record = AgentPendingActionRepository(session).get_by_id(action_id)
        if record is None:
            return False
        state = dict(record.conversation_state or {})
        if state.get("engine") != "pi":
            return False
        state["status"] = decision
        record.conversation_state = state  # 整体重赋值以触发 JSON 列更新
        return True


@router.post("/agent/confirm/{action_id}")
async def agent_confirm(action_id: str):
    """确认执行 Agent 挂起的操作（修⑤：持久化 tool/assistant 消息）"""
    if _resolve_pi_action(action_id, "approved"):
        return {"ok": True, "status": "approved"}
    conversation_id = _resolve_conversation_id_from_action(action_id)
    return StreamingResponse(
        _stream_with_save_for_action(conversation_id, lambda: confirm_action(action_id)),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.post("/agent/reject/{action_id}")
async def agent_reject(action_id: str):
    """拒绝 Agent 挂起的操作（修⑤：持久化 tool/assistant 消息）"""
    if _resolve_pi_action(action_id, "rejected"):
        return {"ok": True, "status": "rejected"}
    conversation_id = _resolve_conversation_id_from_action(action_id)
    return StreamingResponse(
        _stream_with_save_for_action(conversation_id, lambda: reject_action(action_id)),
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
