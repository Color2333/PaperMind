"""标签管理路由（业务在 application/commands/tags.py）"""

from __future__ import annotations

from uuid import UUID  # noqa: TC003 —— FastAPI 路径参数运行期解析

from fastapi import APIRouter, HTTPException, Query

from packages.application.commands import tags as tag_commands
from packages.domain.exceptions import NotFoundError
from packages.storage.db import session_scope

router = APIRouter()

_HEX_COLOR_PATTERN = r"^#(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})$"


@router.get("/tags")
def list_tags() -> dict:
    with session_scope() as session:
        return tag_commands.list_tags(session)


@router.post("/tags")
def create_tag(
    name: str = Query(..., min_length=1, max_length=64),
    color: str = Query(default="#3b82f6", pattern=_HEX_COLOR_PATTERN),
) -> dict:
    try:
        with session_scope() as session:
            return tag_commands.create_tag(session, name=name, color=color)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.patch("/tags/{tag_id}")
def update_tag(
    tag_id: UUID,
    name: str | None = Query(default=None, max_length=64),
    color: str | None = Query(default=None, pattern=_HEX_COLOR_PATTERN),
) -> dict:
    try:
        with session_scope() as session:
            return tag_commands.update_tag(session, tag_id=str(tag_id), name=name, color=color)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/tags/{tag_id}")
def delete_tag(tag_id: UUID) -> dict:
    try:
        with session_scope() as session:
            return tag_commands.delete_tag(session, tag_id=str(tag_id))
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/papers/{paper_id}/tags")
def get_paper_tags(paper_id: UUID) -> dict:
    try:
        with session_scope() as session:
            return tag_commands.get_paper_tags(session, paper_id=paper_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/papers/{paper_id}/tags")
def add_paper_tag(paper_id: UUID, tag_id: UUID) -> dict:
    try:
        with session_scope() as session:
            return tag_commands.add_paper_tag(session, paper_id=paper_id, tag_id=tag_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/papers/{paper_id}/tags/{tag_id}")
def remove_paper_tag(paper_id: UUID, tag_id: UUID) -> dict:
    try:
        with session_scope() as session:
            return tag_commands.remove_paper_tag(session, paper_id=paper_id, tag_id=tag_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/papers/{paper_id}/tags/batch")
def batch_update_paper_tags(paper_id: UUID, tag_ids: list[UUID]) -> dict:
    try:
        with session_scope() as session:
            return tag_commands.batch_update_paper_tags(session, paper_id=paper_id, tag_ids=tag_ids)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
