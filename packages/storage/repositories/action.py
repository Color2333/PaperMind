"""
论文入库行动记录数据仓储
@author Color2333
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import func, select

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from packages.domain.enums import ActionType

from packages.storage.models import ActionPaper, CollectionAction, Paper


class ActionRepository:
    """论文入库行动记录的数据仓储"""

    def __init__(self, session: Session):
        self.session = session

    def create_action(
        self,
        action_type: ActionType,
        title: str,
        paper_ids: list[str],
        query: str | None = None,
        topic_id: str | None = None,
    ) -> CollectionAction:
        """创建一条行动记录并关联论文"""
        action = CollectionAction(
            action_type=action_type,
            title=title,
            query=query,
            topic_id=topic_id,
            paper_count=len(paper_ids),
        )
        self.session.add(action)
        self.session.flush()

        # 批量插入关联论文
        action_papers = [ActionPaper(action_id=action.id, paper_id=pid) for pid in paper_ids]
        self.session.add_all(action_papers)
        self.session.flush()
        return action

    def list_actions(
        self,
        action_type: str | None = None,
        topic_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[CollectionAction], int]:
        """分页列出行动记录"""
        base = select(CollectionAction)
        count_q = select(func.count()).select_from(CollectionAction)

        if action_type:
            base = base.where(CollectionAction.action_type == action_type)
            count_q = count_q.where(CollectionAction.action_type == action_type)
        if topic_id:
            base = base.where(CollectionAction.topic_id == topic_id)
            count_q = count_q.where(CollectionAction.topic_id == topic_id)

        total = self.session.execute(count_q).scalar() or 0
        rows = (
            self.session.execute(
                base.order_by(CollectionAction.created_at.desc()).limit(limit).offset(offset)
            )
            .scalars()
            .all()
        )
        return list(rows), total

    def get_action(self, action_id: str) -> CollectionAction | None:
        return self.session.get(CollectionAction, action_id)

    def get_paper_ids_by_action(self, action_id: str) -> list[str]:
        """获取某次行动关联的所有论文 ID"""
        rows = (
            self.session.execute(
                select(ActionPaper.paper_id).where(ActionPaper.action_id == action_id)
            )
            .scalars()
            .all()
        )
        return list(rows)

    def get_papers_by_action(
        self,
        action_id: str,
        limit: int = 200,
    ) -> list[Paper]:
        """获取某次行动关联的论文列表"""
        rows = (
            self.session.execute(
                select(Paper)
                .join(ActionPaper, Paper.id == ActionPaper.paper_id)
                .where(ActionPaper.action_id == action_id)
                .order_by(Paper.created_at.desc())
                .limit(limit)
            )
            .scalars()
            .all()
        )
        return list(rows)
