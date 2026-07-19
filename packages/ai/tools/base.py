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
    """校验 paper_id（支持短 ID 前缀）+ 查库。

    返回的 paper 对象已从 session expunge（detached），但其所有列属性在
    session 内已加载，离开 session 后访问 title/abstract/embedding 等不会
    触发 lazy load（Paper 无 relationship 字段，全是普通列）。
    修 detached session bug：此前 return paper 后 session 关闭，handler
    访问 paper.title 报 "Instance not bound to a Session"。
    """
    pid, err = _resolve_paper_id(paper_id)
    if err:
        return None, ToolResult(success=False, summary=err)
    assert pid is not None
    with session_scope() as session:
        try:
            paper = PaperRepository(session).get_by_id(pid)
            # 在 session 关闭前 expunge，让 paper 带着已加载的列属性离开。
            # 触发所有列属性加载（防 expunge 后访问未加载列报错）：
            _ = (
                paper.id,
                paper.title,
                paper.arxiv_id,
                paper.abstract,
                paper.pdf_path,
                paper.publication_date,
                paper.embedding,
                paper.read_status,
                paper.metadata_json,
                paper.favorited,
                paper.rejected,
                paper.source,
                paper.source_id,
                paper.doi,
            )
            session.expunge(paper)
            return paper, None
        except ValueError:
            return None, ToolResult(
                success=False,
                summary=f"论文 {paper_id[:8]}... 不存在",
            )
