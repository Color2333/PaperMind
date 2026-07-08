"""
引用关系数据仓储
@author Color2333
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from packages.storage.models import Citation


class CitationRepository:
    def __init__(self, session: Session):
        self.session = session

    def upsert_edge(
        self,
        source_paper_id: str,
        target_paper_id: str,
        context: str | None = None,
    ) -> None:
        q = select(Citation).where(
            Citation.source_paper_id == source_paper_id,
            Citation.target_paper_id == target_paper_id,
        )
        found = self.session.execute(q).scalar_one_or_none()
        if found:
            if context:
                found.context = context
            return
        self.session.add(
            Citation(
                source_paper_id=source_paper_id,
                target_paper_id=target_paper_id,
                context=context,
            )
        )

    def list_all(self, limit: int = 10000) -> list[Citation]:
        """
        查询所有引用关系（带分页限制）

        Args:
            limit: 最大返回数量，默认 10000

        Returns:
            引用关系列表
        """
        q = select(Citation).order_by(Citation.source_paper_id).limit(limit)
        return list(self.session.execute(q).scalars())

    def list_for_paper_ids(self, paper_ids: list[str]) -> list[Citation]:
        if not paper_ids:
            return []
        q = select(Citation).where(
            Citation.source_paper_id.in_(paper_ids) | Citation.target_paper_id.in_(paper_ids)
        )
        return list(self.session.execute(q).scalars())
