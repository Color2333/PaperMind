"""标签管理路由
@author Color2333
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from packages.storage.db import session_scope
from packages.storage.repositories import PaperRepository, TagRepository

router = APIRouter()


@router.get("/tags")
def list_tags() -> dict:
    """获取所有标签列表"""
    with session_scope() as session:
        repo = TagRepository(session)
        tags = repo.list_all()
        return {
            "items": [
                {
                    "id": tag.id,
                    "name": tag.name,
                    "color": tag.color,
                    "paper_count": getattr(tag, "paper_count", 0),
                    "created_at": tag.created_at.isoformat() if tag.created_at else None,
                    "updated_at": tag.updated_at.isoformat() if tag.updated_at else None,
                }
                for tag in tags
            ]
        }


@router.post("/tags")
def create_tag(name: str, color: str = Query(default="#3b82f6")) -> dict:
    """创建新标签"""
    if not name or not name.strip():
        raise HTTPException(status_code=400, detail="标签名称不能为空")
    with session_scope() as session:
        repo = TagRepository(session)
        try:
            tag = repo.create(name.strip(), color)
            return {
                "id": tag.id,
                "name": tag.name,
                "color": tag.color,
                "paper_count": 0,
            }
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e


@router.patch("/tags/{tag_id}")
def update_tag(
    tag_id: UUID,
    name: str | None = Query(default=None),
    color: str | None = Query(default=None),
) -> dict:
    """更新标签"""
    with session_scope() as session:
        repo = TagRepository(session)
        try:
            tag = repo.update(str(tag_id), name=name, color=color)
            paper_count = repo.get_paper_count(str(tag_id))
            return {
                "id": tag.id,
                "name": tag.name,
                "color": tag.color,
                "paper_count": paper_count,
            }
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e


@router.delete("/tags/{tag_id}")
def delete_tag(tag_id: UUID) -> dict:
    """删除标签"""
    with session_scope() as session:
        repo = TagRepository(session)
        tag = repo.get_by_id(str(tag_id))
        if tag is None:
            raise HTTPException(status_code=404, detail="标签不存在")
        repo.delete(str(tag_id))
        return {"deleted": str(tag_id), "name": tag.name}


@router.get("/papers/{paper_id}/tags")
def get_paper_tags(paper_id: UUID) -> dict:
    """获取论文的标签"""
    with session_scope() as session:
        paper_repo = PaperRepository(session)
        try:
            paper_repo.get_by_id(paper_id)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e

        tags_map = paper_repo.get_tags_for_papers([str(paper_id)])
        return {"items": tags_map.get(str(paper_id), [])}


@router.post("/papers/{paper_id}/tags")
def add_paper_tag(paper_id: UUID, tag_id: UUID) -> dict:
    """为论文添加标签"""
    with session_scope() as session:
        paper_repo = PaperRepository(session)
        tag_repo = TagRepository(session)

        try:
            paper_repo.get_by_id(paper_id)
        except ValueError as e:
            raise HTTPException(status_code=404, detail="论文不存在") from e

        tag = tag_repo.get_by_id(str(tag_id))
        if tag is None:
            raise HTTPException(status_code=404, detail="标签不存在")

        paper_repo.link_to_tag(str(paper_id), str(tag_id))
        session.commit()

        return {
            "paper_id": str(paper_id),
            "tag": {
                "id": tag.id,
                "name": tag.name,
                "color": tag.color,
            },
        }


@router.delete("/papers/{paper_id}/tags/{tag_id}")
def remove_paper_tag(paper_id: UUID, tag_id: UUID) -> dict:
    """移除论文的标签"""
    with session_scope() as session:
        paper_repo = PaperRepository(session)
        tag_repo = TagRepository(session)

        try:
            paper_repo.get_by_id(paper_id)
        except ValueError as e:
            raise HTTPException(status_code=404, detail="论文不存在") from e

        tag = tag_repo.get_by_id(str(tag_id))
        if tag is None:
            raise HTTPException(status_code=404, detail="标签不存在")

        paper_repo.unlink_from_tag(str(paper_id), str(tag_id))
        session.commit()

        return {
            "paper_id": str(paper_id),
            "tag_id": str(tag_id),
            "removed": True,
        }


@router.post("/papers/{paper_id}/tags/batch")
def batch_update_paper_tags(paper_id: UUID, tag_ids: list[UUID]) -> dict:
    """批量更新论文的标签（替换所有标签）"""
    with session_scope() as session:
        paper_repo = PaperRepository(session)
        tag_repo = TagRepository(session)

        try:
            paper_repo.get_by_id(paper_id)
        except ValueError as e:
            raise HTTPException(status_code=404, detail="论文不存在") from e

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
        return {
            "paper_id": str(paper_id),
            "items": updated_tags,
        }
