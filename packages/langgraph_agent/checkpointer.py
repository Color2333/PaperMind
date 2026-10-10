"""Checkpointer 单例：PostgresSaver（生产）或 MemorySaver（测试/SQLite）。

PostgresSaver 用 psycopg v3（与核心 psycopg2-binary 并存）。
thread_id = conversation_id（复用现有 AgentConversation.id）。

@author Color2333
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_saver: Any = None


def get_checkpointer() -> Any:
    """单例 checkpointer。生产用 PostgresSaver，SQLite/测试回退 MemorySaver。"""
    global _saver
    if _saver is not None:
        return _saver

    from packages.config import get_settings

    db_url = get_settings().database_url
    if db_url.startswith("sqlite"):
        # 测试/本地 SQLite 环境：内存 checkpointer
        from langgraph.checkpoint.memory import MemorySaver

        _saver = MemorySaver()
        logger.info("LangGraph checkpointer: MemorySaver（SQLite 环境）")
        return _saver

    # 生产 PG：PostgresSaver（psycopg v3）
    # postgresql+psycopg2://... → postgresql://...（psycopg v3 接受标准前缀）
    uri = db_url.replace("postgresql+psycopg2://", "postgresql://")
    try:
        from langgraph.checkpoint.postgres import PostgresSaver

        _saver = PostgresSaver.from_conn_string(uri)
        _saver.setup()  # 首次自建 checkpoint_* 表（幂等）
        logger.info("LangGraph checkpointer: PostgresSaver（已 setup()）")
    except Exception as exc:
        logger.warning("PostgresSaver 初始化失败，回退 MemorySaver: %s", exc)
        from langgraph.checkpoint.memory import MemorySaver

        _saver = MemorySaver()
    return _saver


def reset_checkpointer_for_test() -> None:
    """测试用：重置单例（每个测试用独立 MemorySaver）。"""
    global _saver
    _saver = None


__all__ = ["get_checkpointer", "reset_checkpointer_for_test"]
