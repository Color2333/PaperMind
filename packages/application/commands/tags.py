"""标签管理命令（B8 后期，设计② ManageTags）"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from packages.domain.exceptions import NotFoundError

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.orm import Session


def _tag_dict(tag: Any) -> dict[str, Any]:
    return {
        "id": tag.id,
        "name": tag.name,
        "color": tag.color,
        "paper_count": getattr(tag, "paper_count", 0),
        "created_at": tag.created_at.isoformat() if tag.created_at else None,
        "updated_at": tag.updated_at.isoformat() if tag.updated_at else None,
    }


def list_tags(session: Session) -> dict[str, Any]:
    from packages.storage.repositories import TagRepository

    return {"items": [_tag_dict(t) for t in TagRepository(session).list_all()]}


def create_tag(session: Session, *, name: str, color: str) -> dict[str, Any]:
    from packages.storage.repositories import TagRepository

    if not name.strip():
        raise ValueError("标签名称不能为空")
    try:
        tag = TagRepository(session).create(name.strip(), color)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    return {"id": tag.id, "name": tag.name, "color": tag.color, "paper_count": 0}


def update_tag(
    session: Session, *, tag_id: str, name: str | None = None, color: str | None = None
) -> dict[str, Any]:
    from packages.storage.repositories import TagRepository

    repo = TagRepository(session)
    try:
        tag = repo.update(tag_id, name=name, color=color)
    except ValueError as exc:
        raise NotFoundError(str(exc)) from exc
    result = _tag_dict(tag)
    result["paper_count"] = repo.get_paper_count(tag_id)
    return {k: result[k] for k in ("id", "name", "color", "paper_count")}


def delete_tag(session: Session, *, tag_id: str) -> dict[str, Any]:
    from packages.storage.repositories import TagRepository

    repo = TagRepository(session)
    tag = repo.get_by_id(tag_id)
    if tag is None:
        raise NotFoundError("标签不存在")
    repo.delete(tag_id)
    return {"deleted": tag_id, "name": tag.name}


def get_paper_tags(session: Session, paper_id: UUID) -> dict[str, Any]:
    from packages.storage.repositories import PaperRepository

    repo = PaperRepository(session)
    try:
        repo.get_by_id(paper_id)
    except ValueError as exc:
        raise NotFoundError(str(exc)) from exc
    tags_map = repo.get_tags_for_papers([str(paper_id)])
    return {"items": tags_map.get(str(paper_id), [])}


def add_paper_tag(session: Session, *, paper_id: UUID, tag_id: UUID) -> dict[str, Any]:
    from packages.storage.repositories import PaperRepository, TagRepository

    paper_repo = PaperRepository(session)
    tag_repo = TagRepository(session)
    try:
        paper_repo.get_by_id(paper_id)
    except ValueError as exc:
        raise NotFoundError("论文不存在") from exc
    tag = tag_repo.get_by_id(str(tag_id))
    if tag is None:
        raise NotFoundError("标签不存在")
    paper_repo.link_to_tag(str(paper_id), str(tag_id))
    session.commit()
    return {
        "paper_id": str(paper_id),
        "tag": {"id": tag.id, "name": tag.name, "color": tag.color},
    }


def remove_paper_tag(session: Session, *, paper_id: UUID, tag_id: UUID) -> dict[str, Any]:
    from packages.storage.repositories import PaperRepository, TagRepository

    paper_repo = PaperRepository(session)
    tag_repo = TagRepository(session)
    try:
        paper_repo.get_by_id(paper_id)
    except ValueError as exc:
        raise NotFoundError("论文不存在") from exc
    tag = tag_repo.get_by_id(str(tag_id))
    if tag is None:
        raise NotFoundError("标签不存在")
    paper_repo.unlink_from_tag(str(paper_id), str(tag_id))
    session.commit()
    return {"paper_id": str(paper_id), "tag_id": str(tag_id), "removed": True}


def batch_update_paper_tags(
    session: Session, *, paper_id: UUID, tag_ids: list[UUID]
) -> dict[str, Any]:
    from packages.storage.repositories import PaperRepository, TagRepository

    paper_repo = PaperRepository(session)
    tag_repo = TagRepository(session)
    try:
        paper_repo.get_by_id(paper_id)
    except ValueError as exc:
        raise NotFoundError("论文不存在") from exc

    current_tags = paper_repo.get_tags_for_papers([str(paper_id)]).get(str(paper_id), [])
    current_tag_ids = {t["id"] for t in current_tags}
    new_tag_ids = {str(tid) for tid in tag_ids}

    for tid in current_tag_ids - new_tag_ids:
        paper_repo.unlink_from_tag(str(paper_id), tid)
    for tid in new_tag_ids - current_tag_ids:
        tag = tag_repo.get_by_id(tid)
        if tag:
            paper_repo.link_to_tag(str(paper_id), tid)
    session.commit()

    updated_tags = paper_repo.get_tags_for_papers([str(paper_id)]).get(str(paper_id), [])
    return {"paper_id": str(paper_id), "items": updated_tags}
