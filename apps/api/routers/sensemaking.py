"""
Sensemaking API - 论文认知重构流程
"""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from packages.storage.db import session_scope
from packages.storage.models import SchemaPaperInteraction, SensemakingSession, UserSchema

router = APIRouter(prefix="/sensemaking", tags=["sensemaking"])


class UserSchemaCreate(BaseModel):
    name: str
    user_id: str | None = None
    research_topics: list[str] = []
    academic_level: str | None = None
    current_challenges: list[str] = []
    beliefs: list[str] = []
    knowledge_gaps: list[str] = []


class SensemakingSessionCreate(BaseModel):
    paper_id: str
    user_schema_id: str


@router.post("/schemas")
async def create_user_schema(data: UserSchemaCreate):
    with session_scope() as session:
        schema = UserSchema(
            user_id=data.user_id or "default",
            name=data.name,
            research_topics=data.research_topics,
            academic_level=data.academic_level,
            current_challenges=data.current_challenges,
            beliefs=data.beliefs,
            knowledge_gaps=data.knowledge_gaps,
        )
        session.add(schema)
        session.commit()
        session.refresh(schema)
        return {
            "id": schema.id,
            "user_id": schema.user_id,
            "name": schema.name,
            "research_topics": schema.research_topics,
            "academic_level": schema.academic_level,
            "current_challenges": schema.current_challenges,
            "beliefs": schema.beliefs,
            "knowledge_gaps": schema.knowledge_gaps,
            "version": schema.version,
            "created_at": schema.created_at,
            "updated_at": schema.updated_at,
        }


@router.get("/schemas/{schema_id}")
async def get_user_schema(schema_id: str):
    with session_scope() as session:
        schema = session.query(UserSchema).filter_by(id=schema_id).first()
        if not schema:
            raise HTTPException(status_code=404, detail="Schema not found")
        return {
            "id": schema.id,
            "user_id": schema.user_id,
            "name": schema.name,
            "research_topics": schema.research_topics,
            "academic_level": schema.academic_level,
            "current_challenges": schema.current_challenges,
            "beliefs": schema.beliefs,
            "knowledge_gaps": schema.knowledge_gaps,
            "version": schema.version,
            "created_at": schema.created_at,
            "updated_at": schema.updated_at,
        }


@router.get("/schemas")
async def list_user_schemas(user_id: str | None = None):
    with session_scope() as session:
        query = session.query(UserSchema)
        if user_id:
            query = query.filter_by(user_id=user_id)
        schemas = query.all()
        return [
            {
                "id": s.id,
                "user_id": s.user_id,
                "name": s.name,
                "research_topics": s.research_topics,
                "academic_level": s.academic_level,
                "current_challenges": s.current_challenges,
                "beliefs": s.beliefs,
                "knowledge_gaps": s.knowledge_gaps,
                "version": s.version,
                "created_at": s.created_at,
                "updated_at": s.updated_at,
            }
            for s in schemas
        ]


@router.post("/sessions")
async def create_session(data: SensemakingSessionCreate):
    with session_scope() as session:
        schema = session.query(UserSchema).filter_by(id=data.user_schema_id).first()
        if not schema:
            raise HTTPException(status_code=404, detail="UserSchema not found")

        session_obj = SensemakingSession(
            paper_id=data.paper_id, user_schema_id=data.user_schema_id, status="in_progress"
        )
        session.add(session_obj)
        session.commit()
        session.refresh(session_obj)
        return {
            "id": session_obj.id,
            "paper_id": session_obj.paper_id,
            "user_schema_id": session_obj.user_schema_id,
            "act1_comprehension": session_obj.act1_comprehension,
            "act2_collision": session_obj.act2_collision,
            "act3_reconstruction": session_obj.act3_reconstruction,
            "status": session_obj.status,
            "conversation_history": session_obj.conversation_history,
            "created_at": session_obj.created_at,
            "updated_at": session_obj.updated_at,
            "completed_at": session_obj.completed_at,
        }


@router.get("/sessions/{session_id}")
async def get_session(session_id: str):
    with session_scope() as session:
        session_obj = session.query(SensemakingSession).filter_by(id=session_id).first()
        if not session_obj:
            raise HTTPException(status_code=404, detail="Session not found")
        return {
            "id": session_obj.id,
            "paper_id": session_obj.paper_id,
            "user_schema_id": session_obj.user_schema_id,
            "act1_comprehension": session_obj.act1_comprehension,
            "act2_collision": session_obj.act2_collision,
            "act3_reconstruction": session_obj.act3_reconstruction,
            "status": session_obj.status,
            "conversation_history": session_obj.conversation_history,
            "created_at": session_obj.created_at,
            "updated_at": session_obj.updated_at,
            "completed_at": session_obj.completed_at,
        }


@router.get("/sessions")
async def list_sessions(paper_id: str | None = None, user_schema_id: str | None = None):
    with session_scope() as session:
        query = session.query(SensemakingSession)
        if paper_id:
            query = query.filter_by(paper_id=paper_id)
        if user_schema_id:
            query = query.filter_by(user_schema_id=user_schema_id)
        sessions = query.all()
        return [
            {
                "id": s.id,
                "paper_id": s.paper_id,
                "user_schema_id": s.user_schema_id,
                "act1_comprehension": s.act1_comprehension,
                "act2_collision": s.act2_collision,
                "act3_reconstruction": s.act3_reconstruction,
                "status": s.status,
                "conversation_history": s.conversation_history,
                "created_at": s.created_at,
                "updated_at": s.updated_at,
                "completed_at": s.completed_at,
            }
            for s in sessions
        ]


@router.patch("/sessions/{session_id}/act1")
async def update_act1(session_id: str, act1_data: dict):
    with session_scope() as session:
        session_obj = session.query(SensemakingSession).filter_by(id=session_id).first()
        if not session_obj:
            raise HTTPException(status_code=404, detail="Session not found")

        session_obj.act1_comprehension = act1_data
        session.commit()
        session.refresh(session_obj)
        return {
            "id": session_obj.id,
            "paper_id": session_obj.paper_id,
            "user_schema_id": session_obj.user_schema_id,
            "act1_comprehension": session_obj.act1_comprehension,
            "act2_collision": session_obj.act2_collision,
            "act3_reconstruction": session_obj.act3_reconstruction,
            "status": session_obj.status,
            "conversation_history": session_obj.conversation_history,
            "created_at": session_obj.created_at,
            "updated_at": session_obj.updated_at,
            "completed_at": session_obj.completed_at,
        }


@router.patch("/sessions/{session_id}/act2")
async def update_act2(session_id: str, act2_data: dict):
    with session_scope() as session:
        session_obj = session.query(SensemakingSession).filter_by(id=session_id).first()
        if not session_obj:
            raise HTTPException(status_code=404, detail="Session not found")

        session_obj.act2_collision = act2_data
        session.commit()
        session.refresh(session_obj)
        return {
            "id": session_obj.id,
            "paper_id": session_obj.paper_id,
            "user_schema_id": session_obj.user_schema_id,
            "act1_comprehension": session_obj.act1_comprehension,
            "act2_collision": session_obj.act2_collision,
            "act3_reconstruction": session_obj.act3_reconstruction,
            "status": session_obj.status,
            "conversation_history": session_obj.conversation_history,
            "created_at": session_obj.created_at,
            "updated_at": session_obj.updated_at,
            "completed_at": session_obj.completed_at,
        }


@router.patch("/sessions/{session_id}/act3")
async def complete_act3(session_id: str, act3_data: dict):
    with session_scope() as session:
        session_obj = session.query(SensemakingSession).filter_by(id=session_id).first()
        if not session_obj:
            raise HTTPException(status_code=404, detail="Session not found")

        session_obj.act3_reconstruction = act3_data
        session_obj.status = "completed"
        session_obj.completed_at = datetime.now(UTC)
        session.commit()
        session.refresh(session_obj)
        return {
            "id": session_obj.id,
            "paper_id": session_obj.paper_id,
            "user_schema_id": session_obj.user_schema_id,
            "act1_comprehension": session_obj.act1_comprehension,
            "act2_collision": session_obj.act2_collision,
            "act3_reconstruction": session_obj.act3_reconstruction,
            "status": session_obj.status,
            "conversation_history": session_obj.conversation_history,
            "created_at": session_obj.created_at,
            "updated_at": session_obj.updated_at,
            "completed_at": session_obj.completed_at,
        }


@router.post("/interactions")
async def create_interaction(
    user_schema_id: str,
    paper_id: str,
    interaction_type: str,
    cognitive_delta: dict | None = None,
):
    with session_scope() as session:
        interaction = SchemaPaperInteraction(
            user_schema_id=user_schema_id,
            paper_id=paper_id,
            interaction_type=interaction_type,
            cognitive_delta=cognitive_delta,
        )
        session.add(interaction)
        session.commit()
        session.refresh(interaction)
        return {"id": interaction.id, "status": "created"}
