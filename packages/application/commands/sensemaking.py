"""认知重构命令（B8 后期，设计② SensemakingAct）"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from packages.domain.exceptions import NotFoundError

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from packages.storage.models import SensemakingSession, UserSchema  # noqa: TC004


def _session_dict(s: SensemakingSession) -> dict[str, Any]:
    return {
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


def _schema_dict(s: UserSchema) -> dict[str, Any]:
    return {
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


def create_user_schema(session: Session, *, data: dict[str, Any]) -> dict[str, Any]:
    from packages.storage.models import UserSchema

    schema = UserSchema(
        user_id=data.get("user_id") or "default",
        name=data["name"],
        research_topics=data.get("research_topics", []),
        academic_level=data.get("academic_level"),
        current_challenges=data.get("current_challenges", []),
        beliefs=data.get("beliefs", []),
        knowledge_gaps=data.get("knowledge_gaps", []),
    )
    session.add(schema)
    session.commit()
    session.refresh(schema)
    return _schema_dict(schema)


def get_user_schema(session: Session, schema_id: str) -> dict[str, Any]:
    schema = session.query(UserSchema).filter_by(id=schema_id).first()
    if not schema:
        raise NotFoundError("Schema not found")
    return _schema_dict(schema)


def list_user_schemas(session: Session, *, user_id: str | None = None) -> list[dict[str, Any]]:
    query = session.query(UserSchema)
    if user_id:
        query = query.filter_by(user_id=user_id)
    return [_schema_dict(s) for s in query.all()]


def create_session(session: Session, *, paper_id: str, user_schema_id: str) -> dict[str, Any]:
    from packages.storage.models import SensemakingSession

    schema = session.query(UserSchema).filter_by(id=user_schema_id).first()
    if not schema:
        raise NotFoundError("UserSchema not found")
    session_obj = SensemakingSession(
        paper_id=paper_id, user_schema_id=user_schema_id, status="in_progress"
    )
    session.add(session_obj)
    session.commit()
    session.refresh(session_obj)
    return _session_dict(session_obj)


def get_session(session: Session, session_id: str) -> dict[str, Any]:
    session_obj = session.query(SensemakingSession).filter_by(id=session_id).first()
    if not session_obj:
        raise NotFoundError("Session not found")
    return _session_dict(session_obj)


def list_sessions(
    session: Session, *, paper_id: str | None = None, user_schema_id: str | None = None
) -> list[dict[str, Any]]:
    query = session.query(SensemakingSession)
    if paper_id:
        query = query.filter_by(paper_id=paper_id)
    if user_schema_id:
        query = query.filter_by(user_schema_id=user_schema_id)
    return [_session_dict(s) for s in query.all()]


def update_act(session: Session, *, session_id: str, act: str, data: dict) -> dict[str, Any]:
    """通用 Act 更新（act1/act2/act3）"""
    from packages.storage.models import SensemakingSession

    session_obj = session.query(SensemakingSession).filter_by(id=session_id).first()
    if not session_obj:
        raise NotFoundError("Session not found")
    if act == "act1":
        session_obj.act1_comprehension = data
    elif act == "act2":
        session_obj.act2_collision = data
    elif act == "act3":
        session_obj.act3_reconstruction = data
        session_obj.status = "completed"
        session_obj.completed_at = datetime.now(UTC)
    session.commit()
    session.refresh(session_obj)
    return _session_dict(session_obj)


def generate_act(session: Session, *, session_id: str, act: str) -> dict[str, Any]:
    """AI 生成 Act（理解/碰撞/重构）"""
    from packages.ai.sensemaking_service import SensemakingService
    from packages.storage.db import session_scope as _ss
    from packages.storage.models import SensemakingSession as _SMS

    with _ss() as s:
        if not s.query(_SMS).filter_by(id=session_id).first():
            raise NotFoundError("Session not found")

    svc = SensemakingService()
    method = getattr(svc, f"generate_{act}")
    try:
        return method(session_id)
    except ValueError as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            raise NotFoundError(msg) from exc
        raise ValueError(msg) from exc


def create_interaction(
    session: Session,
    *,
    user_schema_id: str,
    paper_id: str,
    interaction_type: str,
    cognitive_delta: dict | None = None,
) -> dict[str, Any]:
    from packages.storage.models import SchemaPaperInteraction

    interaction = SchemaPaperInteraction(
        user_schema_id=user_schema_id,
        paper_id=paper_id,
        interaction_type=interaction_type,
        cognitive_delta=cognitive_delta,
    )
    session.add(interaction)
    session.commit()
    return {"id": interaction.id, "status": "created"}
