"""
持久化生成内容（Wiki / Brief）数据仓储
@author Color2333
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from packages.storage.models import GeneratedContent


class GeneratedContentRepository:
    """持久化生成内容（Wiki / Brief）"""

    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        *,
        content_type: str,
        title: str,
        markdown: str,
        keyword: str | None = None,
        paper_id: str | None = None,
        metadata_json: dict | None = None,
    ) -> GeneratedContent:
        gc = GeneratedContent(
            content_type=content_type,
            title=title,
            markdown=markdown,
            keyword=keyword,
            paper_id=paper_id,
            metadata_json=metadata_json or {},
        )
        self.session.add(gc)
        self.session.flush()
        return gc

    def list_by_type(self, content_type: str, limit: int = 50) -> list[GeneratedContent]:
        q = (
            select(GeneratedContent)
            .where(GeneratedContent.content_type == content_type)
            .order_by(GeneratedContent.created_at.desc())
            .limit(limit)
        )
        return list(self.session.execute(q).scalars())

    def get_by_id(self, content_id: str) -> GeneratedContent:
        gc = self.session.get(GeneratedContent, content_id)
        if gc is None:
            raise ValueError(f"generated_content {content_id} not found")
        return gc

    def delete(self, content_id: str) -> None:
        gc = self.session.get(GeneratedContent, content_id)
        if gc is not None:
            self.session.delete(gc)
