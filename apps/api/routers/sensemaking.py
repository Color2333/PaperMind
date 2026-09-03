"""Sensemaking API - 论文认知重构流程（业务在 application/commands/sensemaking.py）"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from packages.application.commands import sensemaking as sensemaking_commands
from packages.domain.exceptions import NotFoundError
from packages.storage.db import session_scope

router = APIRouter(prefix="/sensemaking", tags=["sensemaking"])


def _404(exc: NotFoundError):
    raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/schemas")
async def create_user_schema(data: dict):
    with session_scope() as session:
        return sensemaking_commands.create_user_schema(session, data=data)


@router.get("/schemas/{schema_id}")
async def get_user_schema(schema_id: str):
    try:
        with session_scope() as session:
            return sensemaking_commands.get_user_schema(session, schema_id)
    except NotFoundError as exc:
        _404(exc)


@router.get("/schemas")
async def list_user_schemas(user_id: str | None = None):
    with session_scope() as session:
        return sensemaking_commands.list_user_schemas(session, user_id=user_id)


@router.post("/sessions")
async def create_session(data: dict):
    try:
        with session_scope() as session:
            return sensemaking_commands.create_session(
                session, paper_id=data["paper_id"], user_schema_id=data["user_schema_id"]
            )
    except NotFoundError as exc:
        _404(exc)


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    try:
        with session_scope() as session:
            return sensemaking_commands.get_session(session, session_id)
    except NotFoundError as exc:
        _404(exc)


@router.get("/sessions")
async def list_sessions(paper_id: str | None = None, user_schema_id: str | None = None):
    with session_scope() as session:
        return sensemaking_commands.list_sessions(
            session, paper_id=paper_id, user_schema_id=user_schema_id
        )


@router.patch("/sessions/{session_id}/act1")
async def update_act1(session_id: str, act1_data: dict):
    try:
        with session_scope() as session:
            return sensemaking_commands.update_act(
                session, session_id=session_id, act="act1", data=act1_data
            )
    except NotFoundError as exc:
        _404(exc)


@router.patch("/sessions/{session_id}/act2")
async def update_act2(session_id: str, act2_data: dict):
    try:
        with session_scope() as session:
            return sensemaking_commands.update_act(
                session, session_id=session_id, act="act2", data=act2_data
            )
    except NotFoundError as exc:
        _404(exc)


@router.patch("/sessions/{session_id}/act3")
async def complete_act3(session_id: str, act3_data: dict):
    try:
        with session_scope() as session:
            return sensemaking_commands.update_act(
                session, session_id=session_id, act="act3", data=act3_data
            )
    except NotFoundError as exc:
        _404(exc)


@router.post("/sessions/{session_id}/act1/generate")
async def generate_act1(session_id: str):
    return await _generate(session_id, "act1")


@router.post("/sessions/{session_id}/act2/generate")
async def generate_act2(session_id: str):
    return await _generate(session_id, "act2")


@router.post("/sessions/{session_id}/act3/generate")
async def generate_act3(session_id: str):
    return await _generate(session_id, "act3")


async def _generate(session_id: str, act: str) -> dict:
    from fastapi import HTTPException as _HTTPException

    try:
        with session_scope() as session:
            return sensemaking_commands.generate_act(session, session_id=session_id, act=act)
    except NotFoundError as exc:
        _404(exc)
    except ValueError as exc:
        raise _HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/interactions")
async def create_interaction(
    user_schema_id: str,
    paper_id: str,
    interaction_type: str,
    cognitive_delta: dict | None = None,
):
    with session_scope() as session:
        return sensemaking_commands.create_interaction(
            session,
            user_schema_id=user_schema_id,
            paper_id=paper_id,
            interaction_type=interaction_type,
            cognitive_delta=cognitive_delta,
        )
