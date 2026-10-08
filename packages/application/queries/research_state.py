"""Research State 只读查询（D4，设计① §8/§10）

四个 application query：GetResearchQuestion / ListClaims / GetClaimEvidence /
DiffResearchState。全部接收调用方 session、返回 plain dict（canonical result）；
HTTP/MCP/CLI 只做协议转换，不重复实现业务语义。

Diff 语义映射（设计① §8）：research_events 是唯一事实源，diff 不读内存、不重算。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import and_, func, or_, select

from packages.domain.enums import (
    ClaimStatus,
    EventAggregate,
    EventType,
    EvidenceStance,
    RelationPredicate,
)
from packages.storage.models import (
    Claim,
    ClaimRelation,
    Evidence,
    Paper,
    ResearchEvent,
    SourceVersion,
)
from packages.storage.repositories import ClaimRepository, ResearchQuestionRepository

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.orm import Session

_RELATION_DIFF: dict[str, str] = {
    RelationPredicate.supports.value: "strengthened",
    RelationPredicate.contradicts.value: "conflict",
    RelationPredicate.supersedes.value: "superseded",
}

_EVIDENCE_DIFF: dict[str, str] = {
    EvidenceStance.supports.value: "strengthened",
    EvidenceStance.contradicts.value: "weakened",
    EvidenceStance.context.value: "context",
}

_EVENT_DIFF: dict[EventType, str] = {
    EventType.claim_proposed: "added",
    EventType.claim_confirmed: "confirmed",
    EventType.claim_revised: "revised",
    EventType.claim_invalidated: "invalidated",
    EventType.retraction_detected: "retraction",
}


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def get_research_question(session: Session, question_id: str) -> dict:
    """问题聚合视图：question + 按 status/certainty 的 claim 统计"""
    question = ResearchQuestionRepository(session).get(question_id)
    status_rows = session.execute(
        select(Claim.status, func.count())
        .where(Claim.research_question_id == question_id)
        .group_by(Claim.status)
    ).all()
    certainty_rows = session.execute(
        select(Claim.certainty, func.count())
        .where(Claim.research_question_id == question_id)
        .group_by(Claim.certainty)
    ).all()
    return {
        "id": question.id,
        "title": question.title,
        "question": question.question,
        "status": str(question.status),
        "watch_terms": question.watch_terms or [],
        "claim_counts": {
            "by_status": {str(status): int(n) for status, n in status_rows},
            "by_certainty": {str(certainty): int(n) for certainty, n in certainty_rows},
        },
        "created_at": _iso(question.created_at),
        "updated_at": _iso(question.updated_at),
    }


def list_claims(
    session: Session,
    question_id: str,
    *,
    statuses: list[ClaimStatus] | None = None,
    limit: int = 100,
) -> dict:
    """问题的 Claim 列表（UUIDv7 主键即时间倒序）+ 每条的证据计数"""
    ResearchQuestionRepository(session).get(question_id)
    claims = ClaimRepository(session).list_by_question(question_id, statuses=statuses)
    if len(claims) > limit:
        claims = claims[:limit]
    claim_ids = [c.id for c in claims]
    counts: dict[str, int] = {}
    if claim_ids:
        rows = session.execute(
            select(Evidence.claim_id, func.count())
            .where(Evidence.claim_id.in_(claim_ids))
            .group_by(Evidence.claim_id)
        ).all()
        counts = {cid: int(n) for cid, n in rows}
    return {
        "question_id": question_id,
        "items": [
            {
                "id": c.id,
                "statement": c.statement,
                "statement_zh": c.statement_zh,
                "origin": str(c.origin),
                "status": str(c.status),
                "certainty": str(c.certainty),
                "evidence_count": counts.get(c.id, 0),
                "superseded_by_id": c.superseded_by_id,
                "run_id": c.run_id,
                "created_at": _iso(c.created_at),
            }
            for c in claims
        ],
    }


def get_claim_evidence(session: Session, claim_id: str) -> dict:
    """Claim + 全部证据（含 SourceVersion 与 Paper 定位信息）——证据追溯主路径"""
    claim = ClaimRepository(session).get(claim_id)
    rows = session.execute(
        select(Evidence, SourceVersion, Paper)
        .join(SourceVersion, Evidence.source_version_id == SourceVersion.id)
        .join(Paper, SourceVersion.paper_id == Paper.id)
        .where(Evidence.claim_id == claim_id)
        .order_by(Evidence.id)
    ).all()
    evidence_items = []
    for evidence, version, paper in rows:
        evidence_items.append(
            {
                "id": evidence.id,
                "kind": str(evidence.kind),
                "stance": str(evidence.stance),
                "locator": evidence.locator or {},
                "quote": evidence.quote,
                "experiment_conditions": evidence.experiment_conditions,
                "extracted_by": str(evidence.extracted_by),
                "source_version": {
                    "id": version.id,
                    "version_label": version.version_label,
                    "external_version": version.external_version,
                    "content_hash": version.content_hash,
                    "paper": {
                        "id": paper.id,
                        "title": paper.title,
                        "arxiv_id": paper.arxiv_id,
                        "doi": paper.doi,
                    },
                },
            }
        )
    return {
        "claim": {
            "id": claim.id,
            "statement": claim.statement,
            "statement_zh": claim.statement_zh,
            "origin": str(claim.origin),
            "status": str(claim.status),
            "certainty": str(claim.certainty),
            "run_id": claim.run_id,
            "user_note": claim.user_note,
            "confirmed_by": claim.confirmed_by,
            "invalidated_reason": claim.invalidated_reason,
            "created_at": _iso(claim.created_at),
        },
        "evidence": evidence_items,
    }


def _diff_item(event: ResearchEvent) -> dict[str, Any]:
    kind = _EVENT_DIFF.get(event.type)
    payload = event.payload or {}
    if event.type is EventType.claim_relation_recorded:
        kind = _RELATION_DIFF.get(str(payload.get("predicate")), "relation")
    elif event.type is EventType.evidence_extracted:
        kind = _EVIDENCE_DIFF.get(str(payload.get("stance")), "context")
    return {
        "id": event.id,
        "event": str(event.type),
        "diff_kind": kind or "other",
        "aggregate_id": event.aggregate_id,
        "actor": event.actor,
        "payload": payload,
        "occurred_at": _iso(event.occurred_at),
    }


def diff_research_state(
    session: Session,
    question_id: str,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict:
    """研究状态 diff：问题下全部 Claim 相关事件 → 新增/加强/削弱/冲突/取代/失效"""
    ResearchQuestionRepository(session).get(question_id)
    claim_ids = list(
        session.execute(select(Claim.id).where(Claim.research_question_id == question_id)).scalars()
    )
    if not claim_ids:
        return {"question_id": question_id, "items": []}

    evidence_ids = list(
        session.execute(select(Evidence.id).where(Evidence.claim_id.in_(claim_ids))).scalars()
    )
    relation_ids = list(
        session.execute(
            select(ClaimRelation.id).where(
                or_(
                    ClaimRelation.subject_claim_id.in_(claim_ids),
                    ClaimRelation.object_claim_id.in_(claim_ids),
                )
            )
        ).scalars()
    )

    conditions = [
        and_(
            ResearchEvent.aggregate_type == EventAggregate.claim,
            ResearchEvent.aggregate_id.in_(claim_ids),
        )
    ]
    if evidence_ids:
        conditions.append(
            and_(
                ResearchEvent.aggregate_type == EventAggregate.evidence,
                ResearchEvent.aggregate_id.in_(evidence_ids),
            )
        )
    if relation_ids:
        conditions.append(
            and_(
                ResearchEvent.aggregate_type == EventAggregate.relation,
                ResearchEvent.aggregate_id.in_(relation_ids),
            )
        )
    query = select(ResearchEvent).where(or_(*conditions)).order_by(ResearchEvent.id)
    if since is not None:
        query = query.where(ResearchEvent.occurred_at >= since)
    if until is not None:
        query = query.where(ResearchEvent.occurred_at <= until)
    events = list(session.execute(query).scalars())

    return {
        "question_id": question_id,
        "items": [_diff_item(event) for event in events],
    }
