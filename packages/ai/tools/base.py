"""Agent 工具共享基础函数。"""

from __future__ import annotations

import logging
from uuid import UUID

from packages.ai.tools.types import ToolResult
from packages.storage.db import session_scope
from packages.storage.repositories import PaperRepository

logger = logging.getLogger(__name__)


def _resolve_paper_id(val: str) -> tuple[UUID | None, str | None]:
    """返回 (uuid, error_msg)。支持完整 UUID 或 ≥8 位前缀模糊匹配。"""
    val = (val or "").strip()
    try:
        return UUID(val), None
    except ValueError:
        pass
    if len(val) < 8 or not all(c in "0123456789abcdef-" for c in val.lower()):
        return None, "无效的 paper_id 格式（需完整 UUID 或 ≥8 位 hex 前缀）"
    from sqlalchemy import select as sa_select

    from packages.storage.models import Paper

    with session_scope() as s:
        rows = list(
            s.execute(sa_select(Paper.id).where(Paper.id.ilike(f"{val}%")).limit(2)).scalars()
        )
    if not rows:
        return None, f"未找到匹配 '{val}' 的论文"
    if len(rows) > 1:
        return None, f"前缀 '{val}' 匹配多篇论文，请使用完整 UUID"
    return UUID(rows[0]), None


def _require_paper(paper_id: str):
    """校验 paper_id（支持短 ID 前缀）+ 查库"""
    pid, err = _resolve_paper_id(paper_id)
    if err:
        return None, ToolResult(success=False, summary=err)
    assert pid is not None
    with session_scope() as session:
        try:
            paper = PaperRepository(session).get_by_id(pid)
            return paper, None
        except ValueError:
            return None, ToolResult(
                success=False,
                summary=f"论文 {paper_id[:8]}... 不存在",
            )
