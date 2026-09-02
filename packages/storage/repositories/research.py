"""Research State 仓储 — 设计①数据契约的落地实现

契约见 docs/plans/2026-09-02-design-1-research-state-data-contract.md。规则：

- 所有状态变更与 research_events 事件在**同一 session** 写入
  （transactional outbox；P0 无消费者，事件即 History/diff 事实源）。
- Claim 状态机在仓储层强制：非法转换抛 ConflictError，缺前置条件抛 ValidationError。
- Evidence 以 fingerprint 幂等：重复添加返回既有行（created=False），不重复发事件。
- confirmed 硬规则：无证据坐标不得 confirmed；papermind 推断只能由用户确认；
  author 声称 + 支持性证据可由规则自动确认。
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from packages.domain.enums import (
    ClaimCertainty,
    ClaimOrigin,
    ClaimStatus,
    EventAggregate,
    EventType,
    EvidenceKind,
    EvidenceStance,
    QuestionStatus,
    RelationOrigin,
    RelationPredicate,
    ResearchRunStatus,
    RunTrigger,
    SourceDetectedBy,
)
from packages.domain.exceptions import ConflictError, NotFoundError, ValidationError
from packages.domain.ids import new_id
from packages.storage.models import (
    Claim,
    ClaimRelation,
    Evidence,
    Paper,
    ResearchEvent,
    ResearchQuestion,
    ResearchRun,
    SourceVersion,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from packages.domain.enums import EventType as EventTypeT


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def _emit(
    session: Session,
    *,
    type: EventTypeT,
    aggregate_type: EventAggregate,
    aggregate_id: str,
    actor: str = "system",
    run_id: str | None = None,
    job_ref: str | None = None,
    attempt_ref: str | None = None,
    payload: dict[str, Any] | None = None,
) -> ResearchEvent:
    """在当前 session 内追加事件——调用方提交时与业务变更同事务落库"""
    event = ResearchEvent(
        type=type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        actor=actor or "system",
        run_id=run_id,
        job_ref=job_ref,
        attempt_ref=attempt_ref,
        payload=payload or {},
    )
    session.add(event)
    # SessionLocal 是 autoflush=False，必须显式 flush，
    # 否则同事务内后续查询（History/diff/outbox 拉取）看不到刚写的事件
    session.flush()
    return event


def _has_locator(locator: dict | None) -> bool:
    return any(v not in (None, "", [], {}) for v in (locator or {}).values())


def evidence_fingerprint(
    claim_id: str, source_version_id: str, kind: EvidenceKind, locator: dict, quote: str | None
) -> str:
    raw = json.dumps(
        {
            "claim_id": claim_id,
            "source_version_id": source_version_id,
            "kind": str(kind),
            "locator": locator,
            "quote": quote or "",
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# papermind 默认保守（决策点 4：默认 insufficient_evidence）；author/user 的声称本身即事实
_DEFAULT_CERTAINTY: dict[ClaimOrigin, ClaimCertainty] = {
    ClaimOrigin.papermind: ClaimCertainty.insufficient_evidence,
    ClaimOrigin.author: ClaimCertainty.established,
    ClaimOrigin.user: ClaimCertainty.established,
}

_TERMINAL_STATUSES = (ClaimStatus.superseded, ClaimStatus.invalidated)


class ResearchQuestionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self, *, title: str, question: str, watch_terms: list | None = None
    ) -> ResearchQuestion:
        _require(bool(title.strip() and question.strip()), "title/question 不能为空")
        row = ResearchQuestion(title=title, question=question, watch_terms=watch_terms or [])
        self.session.add(row)
        self.session.flush()
        return row

    def get(self, question_id: str) -> ResearchQuestion:
        row = self.session.get(ResearchQuestion, question_id)
        if row is None:
            raise NotFoundError(f"ResearchQuestion {question_id} not found")
        return row

    def list_active(self) -> list[ResearchQuestion]:
        return list(
            self.session.execute(
                select(ResearchQuestion)
                .where(ResearchQuestion.status == QuestionStatus.active)
                .order_by(ResearchQuestion.id)
            ).scalars()
        )

    def archive(self, question_id: str) -> ResearchQuestion:
        row = self.get(question_id)
        row.status = QuestionStatus.archived
        return row


class SourceVersionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_for_paper(
        self,
        paper_id: str,
        *,
        content_hash: str,
        version_label: int | None = None,
        external_version: str | None = None,
        doi: str | None = None,
        file_path: str | None = None,
        origin_url: str | None = None,
        detected_by: SourceDetectedBy = SourceDetectedBy.ingest,
        actor: str = "system",
    ) -> SourceVersion:
        if self.session.get(Paper, paper_id) is None:
            raise NotFoundError(f"Paper {paper_id} 不存在，无法建版本")
        if version_label is None:
            current_max = (
                self.session.execute(
                    select(func.max(SourceVersion.version_label)).where(
                        SourceVersion.paper_id == paper_id
                    )
                ).scalar()
                or 0
            )
            version_label = int(current_max) + 1
        # 新版本即当前版本：降级旧 current（不做物理删除，保留版本历史）
        for row in self.session.execute(
            select(SourceVersion).where(
                SourceVersion.paper_id == paper_id, SourceVersion.is_current.is_(True)
            )
        ).scalars():
            row.is_current = False
        sv = SourceVersion(
            paper_id=paper_id,
            version_label=version_label,
            external_version=external_version,
            doi=doi,
            content_hash=content_hash,
            file_path=file_path,
            origin_url=origin_url,
            detected_by=detected_by,
            is_current=True,
        )
        self.session.add(sv)
        self.session.flush()
        if version_label == 1:
            _emit(
                self.session,
                type=EventType.source_added,
                aggregate_type=EventAggregate.source,
                aggregate_id=paper_id,
                actor=actor,
                payload={"source_version_id": sv.id},
            )
        _emit(
            self.session,
            type=EventType.source_version_detected,
            aggregate_type=EventAggregate.source_version,
            aggregate_id=sv.id,
            actor=actor,
            payload={
                "paper_id": paper_id,
                "version_label": version_label,
                "external_version": external_version,
                "content_hash": content_hash,
                "detected_by": str(detected_by),
            },
        )
        return sv

    def get_current(self, paper_id: str) -> SourceVersion | None:
        return self.session.execute(
            select(SourceVersion).where(
                SourceVersion.paper_id == paper_id, SourceVersion.is_current.is_(True)
            )
        ).scalar_one_or_none()

    def list_for_paper(self, paper_id: str) -> list[SourceVersion]:
        return list(
            self.session.execute(
                select(SourceVersion)
                .where(SourceVersion.paper_id == paper_id)
                .order_by(SourceVersion.version_label)
            ).scalars()
        )


class ClaimRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    # ---------- 创建与查询 ----------

    def create(
        self,
        *,
        statement: str,
        origin: ClaimOrigin,
        research_question_id: str | None = None,
        statement_zh: str | None = None,
        certainty: ClaimCertainty | None = None,
        run_id: str | None = None,
        user_note: str | None = None,
        actor: str | None = None,
    ) -> Claim:
        _require(bool(statement and statement.strip()), "Claim statement 不能为空")
        if origin is ClaimOrigin.papermind:
            _require(run_id is not None, "papermind 判断必须关联 research_run（provenance 硬规则）")
        # user 判断创建即 confirmed；author/papermind 从 draft 起步
        status = ClaimStatus.confirmed if origin is ClaimOrigin.user else ClaimStatus.draft
        claim = Claim(
            statement=statement,
            origin=origin,
            research_question_id=research_question_id,
            statement_zh=statement_zh,
            certainty=certainty or _DEFAULT_CERTAINTY[origin],
            run_id=run_id,
            user_note=user_note,
            status=status,
        )
        if status is ClaimStatus.confirmed:
            claim.confirmed_at = _utcnow()
            claim.confirmed_by = actor or "user"
        self.session.add(claim)
        self.session.flush()
        _emit(
            self.session,
            type=EventType.claim_proposed,
            aggregate_type=EventAggregate.claim,
            aggregate_id=claim.id,
            actor=actor or str(origin),
            run_id=run_id,
            payload={
                "statement": statement,
                "origin": str(origin),
                "status": str(status),
                "certainty": str(claim.certainty),
            },
        )
        if status is ClaimStatus.confirmed:
            _emit(
                self.session,
                type=EventType.claim_confirmed,
                aggregate_type=EventAggregate.claim,
                aggregate_id=claim.id,
                actor=actor or "user",
                run_id=run_id,
                payload={"via": "user_created"},
            )
        return claim

    def get(self, claim_id: str) -> Claim:
        claim = self.session.get(Claim, claim_id)
        if claim is None:
            raise NotFoundError(f"Claim {claim_id} not found")
        return claim

    def list_by_question(
        self, question_id: str, *, statuses: list[ClaimStatus] | None = None
    ) -> list[Claim]:
        q = select(Claim).where(Claim.research_question_id == question_id).order_by(Claim.id.desc())
        if statuses:
            q = q.where(Claim.status.in_(statuses))
        return list(self.session.execute(q).scalars())

    def count_by_status(self, question_id: str) -> dict[str, int]:
        rows = self.session.execute(
            select(Claim.status, func.count())
            .where(Claim.research_question_id == question_id)
            .group_by(Claim.status)
        ).all()
        return {str(status): int(count) for status, count in rows}

    # ---------- 证据 ----------

    def add_evidence(
        self,
        claim_id: str,
        *,
        source_version_id: str,
        kind: EvidenceKind,
        stance: EvidenceStance,
        locator: dict,
        quote: str | None = None,
        experiment_conditions: dict | None = None,
        extracted_by: ClaimOrigin = ClaimOrigin.papermind,
        run_id: str | None = None,
        image_analysis_id: str | None = None,
        actor: str = "system",
    ) -> tuple[Evidence, bool]:
        """添加证据；幂等（fingerprint 命中返回既有行）。同时应用证据规则：
        draft → pending_verification；author + supports → 自动 confirmed。"""
        claim = self.get(claim_id)
        _require(claim.status not in _TERMINAL_STATUSES, "已取代/已失效的 Claim 不再接受新证据")
        _require(
            _has_locator(locator),
            "证据必须有至少一项定位坐标（page/section/figure/table/eq/bbox）",
        )
        _require(
            source_version_id and self.session.get(SourceVersion, source_version_id) is not None,
            "证据必须挂已存在的 source_version",
        )
        fingerprint = evidence_fingerprint(claim_id, source_version_id, kind, locator, quote)
        existing = self.session.execute(
            select(Evidence).where(Evidence.fingerprint == fingerprint)
        ).scalar_one_or_none()
        if existing is not None:
            return existing, False
        evidence = Evidence(
            claim_id=claim_id,
            source_version_id=source_version_id,
            kind=kind,
            stance=stance,
            locator=locator,
            quote=quote,
            experiment_conditions=experiment_conditions,
            extracted_by=extracted_by,
            run_id=run_id,
            image_analysis_id=image_analysis_id,
            fingerprint=fingerprint,
        )
        self.session.add(evidence)
        self.session.flush()
        _emit(
            self.session,
            type=EventType.evidence_extracted,
            aggregate_type=EventAggregate.evidence,
            aggregate_id=evidence.id,
            actor=actor,
            run_id=run_id,
            payload={
                "claim_id": claim_id,
                "kind": str(kind),
                "stance": str(stance),
                "locator": locator,
            },
        )
        self._apply_evidence_rule(claim, evidence)
        return evidence, True

    def _apply_evidence_rule(self, claim: Claim, evidence: Evidence) -> None:
        if claim.origin is ClaimOrigin.user or claim.status in (
            ClaimStatus.confirmed,
            *_TERMINAL_STATUSES,
        ):
            return
        # author 声称 + 坐标完整的支持性证据 → 规则自动确认（设计① §5 决策点 1）
        if claim.origin is ClaimOrigin.author and evidence.stance is EvidenceStance.supports:
            claim.status = ClaimStatus.confirmed
            claim.confirmed_at = _utcnow()
            claim.confirmed_by = "rule:auto_author"
            _emit(
                self.session,
                type=EventType.claim_confirmed,
                aggregate_type=EventAggregate.claim,
                aggregate_id=claim.id,
                actor="rule:auto_author",
                run_id=claim.run_id,
                payload={"via": "auto_author", "evidence_id": evidence.id},
            )
            return
        if claim.status is ClaimStatus.draft:
            claim.status = ClaimStatus.pending_verification

    # ---------- 状态机 ----------

    def confirm(self, claim_id: str, *, actor: str = "user") -> Claim:
        claim = self.get(claim_id)
        if actor != "user":
            raise ConflictError("只有用户可以确认 Claim（自动规则见 add_evidence）")
        _require(
            claim.status in (ClaimStatus.draft, ClaimStatus.pending_verification),
            f"状态 {claim.status} 不可确认",
        )
        # locator 完整性在写入侧强制，此处只要求存在证据
        evidence_count = (
            self.session.execute(
                select(func.count()).select_from(Evidence).where(Evidence.claim_id == claim_id)
            ).scalar()
            or 0
        )
        _require(evidence_count > 0, "无证据坐标的判断不能 confirmed（设计① 硬规则）")
        claim.status = ClaimStatus.confirmed
        claim.confirmed_at = _utcnow()
        claim.confirmed_by = actor
        _emit(
            self.session,
            type=EventType.claim_confirmed,
            aggregate_type=EventAggregate.claim,
            aggregate_id=claim.id,
            actor=actor,
            run_id=claim.run_id,
            payload={"via": "manual"},
        )
        return claim

    def revise(
        self,
        claim_id: str,
        *,
        new_statement: str,
        actor: str = "user",
        statement_zh: str | None = None,
        run_id: str | None = None,
        user_note: str | None = None,
    ) -> Claim:
        """修订 = 建立新版本 Claim + supersedes 关系 + 旧版置 superseded"""
        old = self.get(claim_id)
        _require(old.status not in _TERMINAL_STATUSES, "已取代/已失效的 Claim 不能再修订")
        if actor == "user":
            new_origin, relation_origin = ClaimOrigin.user, RelationOrigin.user
        else:
            new_origin, relation_origin = ClaimOrigin.papermind, RelationOrigin.papermind
            _require(run_id is not None, "papermind 修订必须关联 research_run")
        effective_run = run_id or old.run_id
        new_claim = self.create(
            statement=new_statement,
            origin=new_origin,
            research_question_id=old.research_question_id,
            statement_zh=statement_zh,
            run_id=effective_run,
            user_note=user_note,
            actor=actor,
        )
        relation, _ = ClaimRelationRepository(self.session).record(
            subject_claim_id=new_claim.id,
            object_claim_id=old.id,
            predicate=RelationPredicate.supersedes,
            origin=relation_origin,
            run_id=effective_run,
        )
        old.status = ClaimStatus.superseded
        old.superseded_by_id = new_claim.id
        _emit(
            self.session,
            type=EventType.claim_revised,
            aggregate_type=EventAggregate.claim,
            aggregate_id=old.id,
            actor=actor,
            run_id=effective_run,
            payload={
                "old_claim_id": old.id,
                "new_claim_id": new_claim.id,
                "old_statement": old.statement,
                "new_statement": new_statement,
                "relation_id": relation.id,
            },
        )
        return new_claim

    def invalidate(
        self, claim_id: str, *, reason: str, actor: str = "user", run_id: str | None = None
    ) -> Claim:
        claim = self.get(claim_id)
        _require(claim.status is not ClaimStatus.invalidated, "Claim 已失效")
        _require(bool(reason and reason.strip()), "失效必须给出原因（invalidated_reason）")
        claim.status = ClaimStatus.invalidated
        claim.invalidated_reason = reason
        _emit(
            self.session,
            type=EventType.claim_invalidated,
            aggregate_type=EventAggregate.claim,
            aggregate_id=claim.id,
            actor=actor,
            run_id=run_id,
            payload={"reason": reason},
        )
        return claim


class ClaimRelationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def record(
        self,
        *,
        subject_claim_id: str,
        object_claim_id: str,
        predicate: RelationPredicate,
        origin: RelationOrigin,
        run_id: str | None = None,
        note: str | None = None,
        actor: str | None = None,
    ) -> tuple[ClaimRelation, bool]:
        _require(subject_claim_id != object_claim_id, "Claim 不能与自己建立关系")
        for cid in (subject_claim_id, object_claim_id):
            if self.session.get(Claim, cid) is None:
                raise NotFoundError(f"Claim {cid} not found")
        existing = self.session.execute(
            select(ClaimRelation).where(
                ClaimRelation.subject_claim_id == subject_claim_id,
                ClaimRelation.object_claim_id == object_claim_id,
                ClaimRelation.predicate == predicate,
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing, False
        relation = ClaimRelation(
            subject_claim_id=subject_claim_id,
            object_claim_id=object_claim_id,
            predicate=predicate,
            origin=origin,
            run_id=run_id,
            note=note,
        )
        self.session.add(relation)
        self.session.flush()
        _emit(
            self.session,
            type=EventType.claim_relation_recorded,
            aggregate_type=EventAggregate.relation,
            aggregate_id=relation.id,
            actor=actor or str(origin),
            run_id=run_id,
            payload={
                "subject_claim_id": subject_claim_id,
                "object_claim_id": object_claim_id,
                "predicate": str(predicate),
            },
        )
        return relation, True

    def list_for_claim(self, claim_id: str) -> tuple[list[ClaimRelation], list[ClaimRelation]]:
        outgoing = list(
            self.session.execute(
                select(ClaimRelation).where(ClaimRelation.subject_claim_id == claim_id)
            ).scalars()
        )
        incoming = list(
            self.session.execute(
                select(ClaimRelation).where(ClaimRelation.object_claim_id == claim_id)
            ).scalars()
        )
        return outgoing, incoming


class ResearchRunRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def start(
        self,
        *,
        kind: str,
        research_question_id: str | None = None,
        trigger: RunTrigger = RunTrigger.manual,
        paper_ids: list[str] | None = None,
        model_policy: dict | None = None,
        job_ref: str | None = None,
    ) -> ResearchRun:
        run = ResearchRun(
            kind=kind,
            research_question_id=research_question_id,
            trigger=trigger,
            paper_ids=paper_ids or [],
            model_policy=model_policy or {},
            job_ref=job_ref,
        )
        self.session.add(run)
        self.session.flush()
        return run

    def get(self, run_id: str) -> ResearchRun:
        run = self.session.get(ResearchRun, run_id)
        if run is None:
            raise NotFoundError(f"ResearchRun {run_id} not found")
        return run

    def complete(
        self,
        run_id: str,
        *,
        status: ResearchRunStatus = ResearchRunStatus.succeeded,
        cost_refs: list | None = None,
        artifact_refs: dict | None = None,
        notes: str | None = None,
        actor: str = "system",
    ) -> ResearchRun:
        run = self.get(run_id)
        run.status = status
        run.finished_at = _utcnow()
        if cost_refs is not None:
            run.cost_refs = cost_refs
        if artifact_refs is not None:
            run.artifact_refs = artifact_refs
        if notes is not None:
            run.notes = notes
        _emit(
            self.session,
            type=EventType.research_run_completed,
            aggregate_type=EventAggregate.run,
            aggregate_id=run.id,
            actor=actor,
            payload={"status": str(status)},
        )
        return run

    def fail(
        self,
        run_id: str,
        *,
        error: str,
        job_ref: str | None = None,
        attempt_ref: str | None = None,
        notes: str | None = None,
        actor: str = "system",
    ) -> ResearchRun:
        run = self.get(run_id)
        run.status = ResearchRunStatus.failed
        run.finished_at = _utcnow()
        if notes is not None:
            run.notes = notes
        _emit(
            self.session,
            type=EventType.job_failed,
            aggregate_type=EventAggregate.run,
            aggregate_id=run.id,
            actor=actor,
            job_ref=job_ref or run.job_ref,
            attempt_ref=attempt_ref,
            payload={"error": error},
        )
        return run


class ResearchEventRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_by_aggregate(
        self, aggregate_type: EventAggregate, aggregate_id: str, *, limit: int = 200
    ) -> list[ResearchEvent]:
        # UUIDv7 主键即时间序
        return list(
            self.session.execute(
                select(ResearchEvent)
                .where(
                    ResearchEvent.aggregate_type == aggregate_type,
                    ResearchEvent.aggregate_id == aggregate_id,
                )
                .order_by(ResearchEvent.id)
                .limit(limit)
            ).scalars()
        )

    def list_unprocessed(self, limit: int = 100) -> list[ResearchEvent]:
        return list(
            self.session.execute(
                select(ResearchEvent)
                .where(ResearchEvent.processed_at.is_(None))
                .order_by(ResearchEvent.id)
                .limit(limit)
            ).scalars()
        )

    def mark_processed(self, event_ids: list[str]) -> int:
        if not event_ids:
            return 0
        rows = list(
            self.session.execute(
                select(ResearchEvent).where(ResearchEvent.id.in_(event_ids))
            ).scalars()
        )
        now = _utcnow()
        for row in rows:
            row.processed_at = now
        self.session.flush()  # autoflush=False：标记后同事务内的查询要能看到
        return len(rows)


__all__ = [
    "ClaimRelationRepository",
    "ClaimRepository",
    "ResearchEventRepository",
    "ResearchQuestionRepository",
    "ResearchRunRepository",
    "SourceVersionRepository",
    "evidence_fingerprint",
    "new_id",
]
