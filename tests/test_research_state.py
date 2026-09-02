"""Research State 数据契约（设计①）仓储层测试

覆盖：UUIDv7 有序性、Claim 状态机（origin × evidence × actor）、证据幂等指纹、
supersede/invalidated 流程、关系去重、SourceVersion 版本切换、ResearchRun 生命周期、
事件与业务变更同事务写入（outbox 规则）。
"""

from __future__ import annotations

import time as _time

import pytest
from sqlalchemy import func, select

from packages.ai.seed_research import seed_sample
from packages.domain.enums import (
    ClaimOrigin,
    ClaimStatus,
    EventAggregate,
    EventType,
    EvidenceKind,
    EvidenceStance,
    ReadStatus,
    RelationOrigin,
    RelationPredicate,
    ResearchRunStatus,
    SourceDetectedBy,
)
from packages.domain.exceptions import ConflictError, NotFoundError, ValidationError
from packages.domain.ids import new_id
from packages.domain.schemas import PaperCreate
from packages.storage.db import session_scope
from packages.storage.models import Claim, Evidence, Paper
from packages.storage.repositories import (
    ClaimRelationRepository,
    ClaimRepository,
    PaperRepository,
    ResearchEventRepository,
    ResearchQuestionRepository,
    ResearchRunRepository,
    SourceVersionRepository,
)


def _mk_paper(session, arxiv_id: str = "2608.0001") -> str:
    paper = Paper(title="Test paper", arxiv_id=arxiv_id, abstract="abstract text")
    session.add(paper)
    session.flush()
    return paper.id


def _mk_run(session, question_id: str | None = None, kind: str = "claim_extraction") -> str:
    run = ResearchRunRepository(session).start(kind=kind, research_question_id=question_id)
    return run.id


def _claim_events(session, claim_id: str) -> list[EventType]:
    return [
        e.type
        for e in ResearchEventRepository(session).list_by_aggregate(EventAggregate.claim, claim_id)
    ]


# ---------- ID ----------


def test_new_id_is_uuid7_and_time_ordered():
    ids = []
    for _ in range(5):
        ids.append(new_id())
        _time.sleep(0.005)
    assert len(set(ids)) == 5
    assert ids == sorted(ids)
    assert int(ids[0][12], 16) == 7  # version nibble


# ---------- Claim 创建与状态机 ----------


def test_papermind_claim_requires_run(isolated_db):
    with session_scope() as session, pytest.raises(ValidationError):
        ClaimRepository(session).create(statement="推断 X", origin=ClaimOrigin.papermind)


def test_user_claim_confirmed_directly_with_events(isolated_db):
    with session_scope() as session:
        claim = ClaimRepository(session).create(
            statement="用户判断：该结论成立", origin=ClaimOrigin.user
        )
        assert claim.status is ClaimStatus.confirmed
        assert claim.confirmed_by == "user"
        assert claim.certainty.value == "established"
        events = _claim_events(session, claim.id)
        assert EventType.claim_proposed in events
        assert EventType.claim_confirmed in events


def test_papermind_claim_defaults_and_cannot_self_confirm(isolated_db):
    with session_scope() as session:
        run_id = _mk_run(session)
        claim = ClaimRepository(session).create(
            statement="模型推断 X", origin=ClaimOrigin.papermind, run_id=run_id
        )
        assert claim.status is ClaimStatus.draft
        assert claim.certainty.value == "insufficient_evidence"
        with pytest.raises(ConflictError):
            ClaimRepository(session).confirm(claim.id, actor="papermind:glm-4.7")


def test_confirm_requires_evidence_and_user(isolated_db):
    with session_scope() as session:
        paper_id = _mk_paper(session)
        sv = SourceVersionRepository(session).create_for_paper(paper_id, content_hash="hash-1")
        run_id = _mk_run(session)
        claim = ClaimRepository(session).create(
            statement="推断 X", origin=ClaimOrigin.papermind, run_id=run_id
        )
        # 无证据 → 硬规则拒绝
        with pytest.raises(ValidationError):
            ClaimRepository(session).confirm(claim.id, actor="user")
        # 补证据后可确认
        ClaimRepository(session).add_evidence(
            claim.id,
            source_version_id=sv.id,
            kind=EvidenceKind.text_passage,
            stance=EvidenceStance.supports,
            locator={"page": 3, "section": "4.1"},
            quote="DER drops by 12% relatively.",
            extracted_by=ClaimOrigin.papermind,
            run_id=run_id,
        )
        confirmed = ClaimRepository(session).confirm(claim.id, actor="user")
        assert confirmed.status is ClaimStatus.confirmed
        assert confirmed.confirmed_by == "user"


def test_author_claim_auto_confirms_on_supporting_evidence_only(isolated_db):
    with session_scope() as session:
        paper_id = _mk_paper(session)
        sv = SourceVersionRepository(session).create_for_paper(paper_id, content_hash="hash-1")
        claim = ClaimRepository(session).create(statement="作者声称 X", origin=ClaimOrigin.author)
        assert claim.status is ClaimStatus.draft
        # 反驳性证据不触发自动确认，只推进到 pending_verification
        ClaimRepository(session).add_evidence(
            claim.id,
            source_version_id=sv.id,
            kind=EvidenceKind.numeric_result,
            stance=EvidenceStance.contradicts,
            locator={"table_no": "2"},
            extracted_by=ClaimOrigin.papermind,
        )
        assert claim.status is ClaimStatus.pending_verification
        # 支持性证据 → 规则自动确认
        ClaimRepository(session).add_evidence(
            claim.id,
            source_version_id=sv.id,
            kind=EvidenceKind.text_passage,
            stance=EvidenceStance.supports,
            locator={"page": 1, "section": "Abstract"},
            quote="We show that X holds.",
            extracted_by=ClaimOrigin.author,
        )
        assert claim.status is ClaimStatus.confirmed
        assert claim.confirmed_by == "rule:auto_author"
        assert EventType.claim_confirmed in _claim_events(session, claim.id)


def test_evidence_requires_locator_and_existing_source_version(isolated_db):
    with session_scope() as session:
        paper_id = _mk_paper(session)
        claim = ClaimRepository(session).create(
            statement="推断 X", origin=ClaimOrigin.papermind, run_id=_mk_run(session)
        )
        with pytest.raises(ValidationError):
            ClaimRepository(session).add_evidence(
                claim.id,
                source_version_id="nonexistent",
                kind=EvidenceKind.text_passage,
                stance=EvidenceStance.supports,
                locator={"page": 1},
            )
        sv = SourceVersionRepository(session).create_for_paper(paper_id, content_hash="hash-1")
        with pytest.raises(ValidationError):
            ClaimRepository(session).add_evidence(
                claim.id,
                source_version_id=sv.id,
                kind=EvidenceKind.text_passage,
                stance=EvidenceStance.supports,
                locator={},
            )


def test_evidence_fingerprint_dedupes_idempotently(isolated_db):
    with session_scope() as session:
        paper_id = _mk_paper(session)
        sv = SourceVersionRepository(session).create_for_paper(paper_id, content_hash="hash-1")
        run_id = _mk_run(session)
        claim = ClaimRepository(session).create(
            statement="推断 X", origin=ClaimOrigin.papermind, run_id=run_id
        )
        kwargs = {
            "source_version_id": sv.id,
            "kind": EvidenceKind.text_passage,
            "stance": EvidenceStance.supports,
            "locator": {"page": 5},
            "quote": "same quote",
            "extracted_by": ClaimOrigin.papermind,
            "run_id": run_id,
        }
        first, created_first = ClaimRepository(session).add_evidence(claim.id, **kwargs)
        second, created_second = ClaimRepository(session).add_evidence(claim.id, **kwargs)
        assert created_first is True
        assert created_second is False
        assert first.id == second.id
        count = session.execute(
            select(func.count()).select_from(Evidence).where(Evidence.claim_id == claim.id)
        ).scalar()
        assert count == 1
        events = list(
            ResearchEventRepository(session).list_by_aggregate(EventAggregate.evidence, first.id)
        )
        assert len(events) == 1  # 重放不重复发事件


# ---------- supersede / invalidate ----------


def test_revise_supersedes_old_claim(isolated_db):
    with session_scope() as session:
        original = ClaimRepository(session).create(statement="初版判断", origin=ClaimOrigin.user)
        revised = ClaimRepository(session).revise(
            original.id, new_statement="修订后的判断", actor="user"
        )
        assert revised.status is ClaimStatus.confirmed
        assert revised.research_question_id is None
        session.flush()
        old = ClaimRepository(session).get(original.id)
        assert old.status is ClaimStatus.superseded
        assert old.superseded_by_id == revised.id
        relations = ClaimRelationRepository(session)
        outgoing, incoming = relations.list_for_claim(revised.id)
        assert any(r.predicate is RelationPredicate.supersedes for r in outgoing)
        assert any(r.object_claim_id == original.id for r in outgoing)
        assert EventType.claim_revised in _claim_events(session, original.id)


def test_revise_by_papermind_requires_run(isolated_db):
    with session_scope() as session:
        original = ClaimRepository(session).create(statement="初版判断", origin=ClaimOrigin.user)
        with pytest.raises(ValidationError):
            ClaimRepository(session).revise(
                original.id, new_statement="模型修订", actor="papermind:glm-4.7"
            )


def test_invalidate_requires_reason_and_records_event(isolated_db):
    with session_scope() as session:
        claim = ClaimRepository(session).create(statement="判断", origin=ClaimOrigin.user)
        with pytest.raises(ValidationError):
            ClaimRepository(session).invalidate(claim.id, reason="  ")
        done = ClaimRepository(session).invalidate(claim.id, reason="后续工作复现失败")
        assert done.status is ClaimStatus.invalidated
        assert done.invalidated_reason == "后续工作复现失败"
        assert EventType.claim_invalidated in _claim_events(session, claim.id)
        with pytest.raises(ValidationError):
            ClaimRepository(session).invalidate(claim.id, reason="重复失效")


# ---------- 关系 ----------


def test_relation_dedupe_and_self_guard(isolated_db):
    with session_scope() as session:
        a = ClaimRepository(session).create(statement="A", origin=ClaimOrigin.user)
        b = ClaimRepository(session).create(statement="B", origin=ClaimOrigin.user)
        repo = ClaimRelationRepository(session)
        with pytest.raises(ValidationError):
            repo.record(
                subject_claim_id=a.id,
                object_claim_id=a.id,
                predicate=RelationPredicate.supports,
                origin=RelationOrigin.user,
            )
        rel, created = repo.record(
            subject_claim_id=b.id,
            object_claim_id=a.id,
            predicate=RelationPredicate.contradicts,
            origin=RelationOrigin.user,
        )
        rel2, created2 = repo.record(
            subject_claim_id=b.id,
            object_claim_id=a.id,
            predicate=RelationPredicate.contradicts,
            origin=RelationOrigin.user,
        )
        assert created is True and created2 is False and rel.id == rel2.id


# ---------- SourceVersion ----------


def test_source_version_flow_and_current_switch(isolated_db):
    with session_scope() as session:
        paper_id = _mk_paper(session)
        repo = SourceVersionRepository(session)
        v1 = repo.create_for_paper(
            paper_id,
            content_hash="hash-v1",
            external_version="v1",
            detected_by=SourceDetectedBy.ingest,
        )
        assert v1.version_label == 1 and v1.is_current
        v2 = repo.create_for_paper(
            paper_id,
            content_hash="hash-v2",
            external_version="v2",
            detected_by=SourceDetectedBy.watch,
        )
        assert v2.version_label == 2
        current = repo.get_current(paper_id)
        assert current is not None and current.id == v2.id
        labels = {row.version_label: row.is_current for row in repo.list_for_paper(paper_id)}
        assert labels == {1: False, 2: True}
        # SourceAdded 只在 v1 发一次；SourceVersionDetected 每版本一条
        source_events = ResearchEventRepository(session).list_by_aggregate(
            EventAggregate.source, paper_id
        )
        assert [e.type for e in source_events].count(EventType.source_added) == 1
        detected = list(
            ResearchEventRepository(session).list_by_aggregate(EventAggregate.source_version, v2.id)
        )
        assert detected[0].type is EventType.source_version_detected
        with pytest.raises(NotFoundError):
            repo.create_for_paper("missing-paper", content_hash="h")


# ---------- ResearchRun ----------


def test_run_lifecycle_events(isolated_db):
    with session_scope() as session:
        repo = ResearchRunRepository(session)
        run = repo.start(kind="claim_extraction", paper_ids=["p1"], model_policy={"model": "x"})
        assert run.status is ResearchRunStatus.running
        done = repo.complete(run.id, cost_refs=["trace-1"], artifact_refs={"report": "r1"})
        assert done.status is ResearchRunStatus.succeeded
        assert done.finished_at is not None
        events = ResearchEventRepository(session).list_by_aggregate(EventAggregate.run, run.id)
        assert events[-1].type is EventType.research_run_completed
        failed = repo.start(kind="skim")
        repo.fail(failed.id, error="boom", job_ref="job-1", attempt_ref="att-1")
        fail_events = ResearchEventRepository(session).list_by_aggregate(
            EventAggregate.run, failed.id
        )
        assert fail_events[-1].type is EventType.job_failed
        assert fail_events[-1].payload["error"] == "boom"
        assert fail_events[-1].job_ref == "job-1"


# ---------- 事件 outbox ----------


def test_events_unprocessed_and_mark_processed(isolated_db):
    with session_scope() as session:
        claim = ClaimRepository(session).create(statement="判断", origin=ClaimOrigin.user)
        del claim
        events_repo = ResearchEventRepository(session)
        pending = events_repo.list_unprocessed()
        assert pending, "业务变更应产生未消费事件"
        processed = events_repo.mark_processed([e.id for e in pending])
        assert processed == len(pending)
        assert events_repo.list_unprocessed() == []


# ---------- question 聚合 ----------


def test_question_claims_aggregation(isolated_db):
    with session_scope() as session:
        q = ResearchQuestionRepository(session).create(
            title="说话人分离", question="哪些方法在 LibriSpeech 上有效？"
        )
        repo = ClaimRepository(session)
        run_id = _mk_run(session, question_id=q.id)
        repo.create(statement="用户结论", origin=ClaimOrigin.user, research_question_id=q.id)
        repo.create(
            statement="模型推断",
            origin=ClaimOrigin.papermind,
            run_id=run_id,
            research_question_id=q.id,
        )
        assert repo.count_by_status(q.id) == {"confirmed": 1, "draft": 1}
        claims = repo.list_by_question(q.id, statuses=[ClaimStatus.draft])
        assert len(claims) == 1 and claims[0].origin is ClaimOrigin.papermind
        # claim 统计里没有丢 confirmed 的用户判断
        total = session.execute(
            select(func.count()).select_from(Claim).where(Claim.research_question_id == q.id)
        ).scalar()
        assert total == 2


# ---------- D2：ingest 建 v1 版本 + 样本种子 ----------


def test_upsert_paper_creates_initial_source_version_idempotently(isolated_db):
    with session_scope() as session:
        repo = PaperRepository(session)
        data = PaperCreate(title="Seed paper", abstract="Some abstract.", arxiv_id="2608.9999")
        p1 = repo.upsert_paper(data)
        versions = SourceVersionRepository(session).list_for_paper(p1.id)
        assert len(versions) == 1
        assert versions[0].version_label == 1 and versions[0].is_current
        # 重复 upsert（已存在分支）不追加版本、不重复发事件
        p2 = repo.upsert_paper(data)
        assert p2.id == p1.id
        assert len(SourceVersionRepository(session).list_for_paper(p1.id)) == 1
        events = ResearchEventRepository(session).list_by_aggregate(EventAggregate.source, p1.id)
        assert [e.type for e in events].count(EventType.source_added) == 1


def test_seed_sample_builds_slice_and_is_idempotent(isolated_db):
    with session_scope() as session:
        abstracts = [
            "Streaming diarization cuts DER by 12% on LibriSpeech. Second sentence.",
            "A survey of end-to-end diarization systems. Second sentence.",
        ]
        for i, abstract in enumerate(abstracts, start=1):
            session.add(
                Paper(
                    title=f"Seed paper {i}",
                    arxiv_id=f"2608.200{i}",
                    abstract=abstract,
                    read_status=ReadStatus.skimmed,
                )
            )
        session.flush()

        stats = seed_sample(session, arxiv_ids=["2608.2001", "2608.2002"])
        assert stats["versions_created"] == 2
        assert stats["author_claims_created"] == 2
        assert stats["meta_claim_created"] == 1
        assert stats["relations_created"] == 2
        # author 判断按规则自动 confirmed；papermind 综合判断保持 draft
        author_claims = (
            session.execute(select(Claim).where(Claim.origin == ClaimOrigin.author)).scalars().all()
        )
        assert all(c.status is ClaimStatus.confirmed for c in author_claims)
        meta = session.execute(
            select(Claim).where(Claim.origin == ClaimOrigin.papermind)
        ).scalar_one()
        assert meta.status is ClaimStatus.draft

        # 重复执行：幂等
        stats2 = seed_sample(session, arxiv_ids=["2608.2001", "2608.2002"])
        assert stats2["versions_created"] == 0
        assert stats2["author_claims_created"] == 0
        assert stats2["meta_claim_created"] == 0
        assert stats2["relations_created"] == 0


def test_seed_sample_dry_run_writes_nothing(isolated_db):
    with session_scope() as session:
        session.add(
            Paper(
                title="Seed paper",
                arxiv_id="2608.3001",
                abstract="A claim worth tracking. More text.",
                read_status=ReadStatus.skimmed,
            )
        )
        session.flush()
        plan = seed_sample(session, arxiv_ids=["2608.3001"], dry_run=True)
        assert plan["dry_run"] is True
        assert plan["versions_to_create"] == 1
        assert session.execute(select(func.count()).select_from(Claim)).scalar() == 0
        assert session.execute(select(func.count()).select_from(Paper)).scalar() == 1


# ---------- D4：diff 查询映射 ----------


def test_diff_research_state_maps_kinds(isolated_db):
    from packages.application.queries.research_state import diff_research_state

    with session_scope() as session:
        q = ResearchQuestionRepository(session).create(title="Q", question="问题？")
        repo = ClaimRepository(session)
        a = repo.create(statement="结论 A", origin=ClaimOrigin.user, research_question_id=q.id)
        b = repo.create(statement="结论 B", origin=ClaimOrigin.user, research_question_id=q.id)
        ClaimRelationRepository(session).record(
            subject_claim_id=b.id,
            object_claim_id=a.id,
            predicate=RelationPredicate.contradicts,
            origin=RelationOrigin.user,
        )
        result = diff_research_state(session, q.id)
        kinds = {item["diff_kind"] for item in result["items"]}
        # user 创建 → added + confirmed；contradicts 关系 → conflict
        assert {"added", "confirmed", "conflict"} <= kinds
        assert all(item["event"] in {e.value for e in EventType} for item in result["items"])
