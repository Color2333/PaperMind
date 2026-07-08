"""
标签数据仓储
@author Color2333
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from packages.storage.models import PaperTag, Tag


class TagRepository:
    """标签数据仓储"""

    def __init__(self, session: Session):
        self.session = session

    def list_all(self) -> list[Tag]:
        """获取所有标签，按使用次数排序"""
        q = (
            select(Tag, func.count(PaperTag.id).label("paper_count"))
            .join(PaperTag, Tag.id == PaperTag.tag_id, isouter=True)
            .group_by(Tag.id)
            .order_by(func.count(PaperTag.id).desc())
        )
        rows = self.session.execute(q).all()
        tags = []
        for row in rows:
            tag = row[0]
            tag.paper_count = row[1] or 0
            tags.append(tag)
        return tags

    def get_by_id(self, tag_id: str) -> Tag | None:
        """根据 ID 获取标签"""
        return self.session.get(Tag, tag_id)

    def get_by_name(self, name: str) -> Tag | None:
        """根据名称获取标签"""
        q = select(Tag).where(Tag.name == name)
        return self.session.execute(q).scalar_one_or_none()

    def create(self, name: str, color: str = "#3b82f6") -> Tag:
        """创建新标签"""
        existing = self.get_by_name(name)
        if existing:
            raise ValueError(f"标签 '{name}' 已存在")
        tag = Tag(name=name, color=color)
        self.session.add(tag)
        self.session.flush()
        return tag

    def update(self, tag_id: str, name: str | None = None, color: str | None = None) -> Tag:
        """更新标签"""
        tag = self.get_by_id(tag_id)
        if tag is None:
            raise ValueError(f"标签 {tag_id} 不存在")
        if name is not None:
            existing = self.get_by_name(name)
            if existing and existing.id != tag_id:
                raise ValueError(f"标签 '{name}' 已存在")
            tag.name = name
        if color is not None:
            tag.color = color
        self.session.flush()
        return tag

    def delete(self, tag_id: str) -> None:
        """删除标签"""
        tag = self.get_by_id(tag_id)
        if tag is not None:
            self.session.delete(tag)

    def get_paper_count(self, tag_id: str) -> int:
        """获取标签关联的论文数量"""
        q = select(func.count()).select_from(PaperTag).where(PaperTag.tag_id == tag_id)
        return self.session.execute(q).scalar() or 0
