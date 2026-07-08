"""
Agent 对话相关数据仓储
@author Color2333
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import delete, select

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from packages.storage.models import (
    AgentConversation,
    AgentMessage,
    AgentPendingAction,
)


class AgentConversationRepository:
    """Agent 对话会话 Repository"""

    def __init__(self, session: Session):
        self.session = session

    def create(self, user_id: str | None = None, title: str | None = None) -> AgentConversation:
        """创建新会话"""
        conv = AgentConversation(user_id=user_id, title=title)
        self.session.add(conv)
        self.session.flush()
        return conv

    def get_by_id(self, conv_id: str) -> AgentConversation | None:
        """根据 ID 获取会话"""
        return self.session.get(AgentConversation, conv_id)

    def list_all(self, user_id: str | None = None, limit: int = 50) -> list[AgentConversation]:
        """获取所有会话（按时间倒序）"""
        q = select(AgentConversation).order_by(AgentConversation.updated_at.desc()).limit(limit)
        return list(self.session.execute(q).scalars())

    def update_title(self, conv_id: str, title: str) -> AgentConversation | None:
        """更新会话标题"""
        conv = self.get_by_id(conv_id)
        if conv:
            conv.title = title
            self.session.flush()
        return conv

    def delete(self, conv_id: str) -> bool:
        """删除会话"""
        conv = self.get_by_id(conv_id)
        if conv:
            self.session.delete(conv)
            self.session.flush()
            return True
        return False


class AgentMessageRepository:
    """Agent 对话消息 Repository"""

    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        conversation_id: str,
        role: str,
        content: str,
        meta: dict | None = None,
    ) -> AgentMessage:
        """创建消息"""
        msg = AgentMessage(
            conversation_id=conversation_id,
            role=role,
            content=content,
            meta=meta,
        )
        self.session.add(msg)
        self.session.flush()
        return msg

    def list_by_conversation(self, conversation_id: str, limit: int = 100) -> list[AgentMessage]:
        """获取会话的所有消息"""
        q = (
            select(AgentMessage)
            .where(AgentMessage.conversation_id == conversation_id)
            .order_by(AgentMessage.created_at.asc())
            .limit(limit)
        )
        return list(self.session.execute(q).scalars())

    def delete_by_conversation(self, conversation_id: str) -> int:
        """删除会话的所有消息"""
        q = delete(AgentMessage).where(AgentMessage.conversation_id == conversation_id)
        result = self.session.execute(q)
        self.session.flush()
        return result.rowcount


class AgentPendingActionRepository:
    """Agent 待确认操作持久化 Repository"""

    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        action_id: str,
        tool_name: str,
        tool_args: dict,
        tool_call_id: str | None = None,
        conversation_id: str | None = None,
        conversation_state: dict | None = None,
    ) -> AgentPendingAction:
        """创建待确认操作"""
        action = AgentPendingAction(
            id=action_id,
            tool_name=tool_name,
            tool_args=tool_args,
            tool_call_id=tool_call_id,
            conversation_id=conversation_id,
            conversation_state=conversation_state,
        )
        self.session.add(action)
        self.session.flush()
        return action

    def get_by_id(self, action_id: str) -> AgentPendingAction | None:
        """根据 ID 获取待确认操作"""
        return self.session.get(AgentPendingAction, action_id)

    def delete(self, action_id: str) -> bool:
        """删除待确认操作"""
        action = self.get_by_id(action_id)
        if action:
            self.session.delete(action)
            self.session.flush()
            return True
        return False

    def cleanup_expired(self, ttl_seconds: int = 1800) -> int:
        """清理过期的待确认操作"""
        cutoff = datetime.now(UTC) - timedelta(seconds=ttl_seconds)
        q = delete(AgentPendingAction).where(AgentPendingAction.created_at < cutoff)
        result = self.session.execute(q)
        self.session.flush()
        return result.rowcount
