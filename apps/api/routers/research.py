"""Research State 只读路由（D4）

只做协议转换：解析参数 → 调 application query → 返回 canonical result。
业务语义（状态、diff 映射、权限）全部在 packages/application/queries。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query

from packages.application.queries import research_state
from packages.domain.enums import ClaimStatus
from packages.storage.db import session_scope

router = APIRouter()


@router.get("/research/questions/{question_id}")
def get_question(question_id: str) -> dict:
    with session_scope() as session:
        return research_state.get_research_question(session, question_id)


@router.get("/research/questions/{question_id}/claims")
def list_question_claims(
    question_id: str,
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict:
    statuses = None
    if status:
        try:
            statuses = [ClaimStatus(status)]
        except ValueError:
            raise HTTPException(status_code=422, detail=f"invalid status: {status}") from None
    with session_scope() as session:
        return research_state.list_claims(session, question_id, statuses=statuses, limit=limit)


@router.get("/research/claims/{claim_id}/evidence")
def get_claim_evidence(claim_id: str) -> dict:
    with session_scope() as session:
        return research_state.get_claim_evidence(session, claim_id)


@router.get("/research/questions/{question_id}/diff")
def diff_question(
    question_id: str,
    since_hours: int | None = Query(default=None, ge=1, le=24 * 365),
) -> dict:
    since = None
    if since_hours:
        since = datetime.now(UTC) - timedelta(hours=since_hours)
    with session_scope() as session:
        return research_state.diff_research_state(session, question_id, since=since)
