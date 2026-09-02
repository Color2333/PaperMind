"""采集行动记录查询（B7，设计② ListActions / GetAction）"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from packages.domain.exceptions import NotFoundError

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def _action_dict(a) -> dict[str, Any]:
    return {
        "id": a.id,
        "action_type": a.action_type,
        "title": a.title,
        "query": a.query,
        "topic_id": a.topic_id,
        "paper_count": a.paper_count,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


def list_actions(
    session: Session,
    *,
    action_type: str | None = None,
    topic_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    from packages.storage.repositories import ActionRepository

    actions, total = ActionRepository(session).list_actions(
        action_type=action_type, topic_id=topic_id, limit=limit, offset=offset
    )
    return {"items": [_action_dict(a) for a in actions], "total": total}


def get_action(session: Session, action_id: str) -> dict[str, Any]:
    from packages.storage.repositories import ActionRepository

    action = ActionRepository(session).get_action(action_id)
    if not action:
        raise NotFoundError("行动记录不存在")
    return _action_dict(action)


def get_action_papers(session: Session, action_id: str, *, limit: int = 200) -> dict[str, Any]:
    from packages.storage.repositories import ActionRepository

    papers = ActionRepository(session).get_papers_by_action(action_id, limit=limit)
    return {
        "action_id": action_id,
        "items": [
            {
                "id": p.id,
                "title": p.title,
                "arxiv_id": p.arxiv_id,
                "publication_date": p.publication_date.isoformat() if p.publication_date else None,
                "read_status": p.read_status,
            }
            for p in papers
        ],
    }
