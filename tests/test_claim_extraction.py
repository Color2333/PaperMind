"""D3：Claim 抽取服务测试——ResearchRun 生成待验证 Claim 的核心链路

覆盖：抽取创建 papermind Claim + 坐标完整 Evidence + Run/Trace provenance；
重复抽取幂等；引用不可核实时保持 draft（不伪造证据坐标）。
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import func, select

from packages.ai.claim_extractor import ClaimExtractionService
from packages.domain.enums import (
    ClaimOrigin,
    ClaimStatus,
    EventAggregate,
    EventType,
    ResearchRunStatus,
)
from packages.domain.exceptions import ValidationError
from packages.domain.schemas import PaperCreate
from packages.integrations.llm_client import LLMClient, LLMResult
from packages.storage.db import session_scope
from packages.storage.models import (
    Claim,
    Evidence,
    PromptTrace,
    ResearchEvent,
    ResearchRun,
)
from packages.storage.repositories import PaperRepository

SOURCE_TEXT = "Streaming transformer diarization reduces DER. Method uses multi-channel fusion."

VALID_CLAIMS = {
    "claims": [
        {
            "statement": "Streaming transformer diarization reduces DER.",
            "statement_zh": "流式 transformer 分离降低了 DER。",
            "quote": "Streaming transformer diarization reduces DER.",
            "locator": {"section": "abstract"},
            "certainty": "conditional",
        },
        {
            "statement": "Method uses multi-channel fusion.",
            "quote": "Method uses multi-channel fusion.",
            "locator": {"section": "3"},
        },
    ]
}


@pytest.fixture()
def fake_llm(monkeypatch):
    def _fake(self, prompt, stage, model_override=None, max_tokens=None):
        payload = VALID_CLAIMS if stage == "claim_extraction" else {"answer": "x"}
        content = json.dumps(payload, ensure_ascii=False)
        return LLMResult(
            content=content,
            parsed_json=payload,
            input_tokens=10,
            output_tokens=5,
            input_cost_usd=0.0,
            output_cost_usd=0.0,
            total_cost_usd=0.0,
        )

    monkeypatch.setattr(LLMClient, "summarize_text", _fake)


def _mk_paper(session, arxiv_id: str = "2608.4001", abstract: str = SOURCE_TEXT) -> str:
    return (
        PaperRepository(session)
        .upsert_paper(PaperCreate(title="Extraction paper", abstract=abstract, arxiv_id=arxiv_id))
        .id
    )


def test_extraction_creates_pending_claims_with_provenance(isolated_db, fake_llm):
    with session_scope() as session:
        paper_id = _mk_paper(session)
        stats = ClaimExtractionService().extract_in_session(
            session, paper_id, source_text=SOURCE_TEXT
        )
        assert stats["claims_created"] == 2
        assert stats["claims_unverified"] == 0

        claims = (
            session.execute(select(Claim).where(Claim.origin == ClaimOrigin.papermind))
            .scalars()
            .all()
        )
        assert len(claims) == 2
        for claim in claims:
            assert claim.status is ClaimStatus.pending_verification
            assert claim.run_id == stats["run_id"]
            evidence = list(
                session.execute(select(Evidence).where(Evidence.claim_id == claim.id)).scalars()
            )
            assert len(evidence) == 1
            assert evidence[0].run_id == stats["run_id"]

        run = session.get(ResearchRun, stats["run_id"])
        assert run.status is ResearchRunStatus.succeeded
        assert run.cost_refs, "cost provenance 应指向 prompt trace"
        assert (
            session.execute(
                select(func.count())
                .select_from(PromptTrace)
                .where(PromptTrace.stage == "claim_extraction")
            ).scalar()
            == 1
        )
        run_events = (
            session.execute(
                select(ResearchEvent).where(
                    ResearchEvent.aggregate_type == EventAggregate.run,
                    ResearchEvent.aggregate_id == stats["run_id"],
                )
            )
            .scalars()
            .all()
        )
        assert any(e.type is EventType.research_run_completed for e in run_events)


def test_extraction_is_idempotent(isolated_db, fake_llm):
    with session_scope() as session:
        paper_id = _mk_paper(session)
        first = ClaimExtractionService().extract_in_session(
            session, paper_id, source_text=SOURCE_TEXT
        )
        second = ClaimExtractionService().extract_in_session(
            session, paper_id, source_text=SOURCE_TEXT
        )
        assert first["claims_created"] == 2
        assert second["claims_created"] == 0
        assert second["claims_skipped"] == 2
        assert (
            session.execute(
                select(func.count()).select_from(Claim).where(Claim.origin == ClaimOrigin.papermind)
            ).scalar()
            == 2
        )


def test_unverifiable_quote_stays_draft_without_evidence(isolated_db, fake_llm, monkeypatch):
    def _bogus(self, prompt, stage, model_override=None, max_tokens=None):
        payload = {
            "claims": [
                {
                    "statement": "Claim with unverifiable quote.",
                    "quote": "This sentence does not exist in the source text.",
                    "locator": {"page": 99},
                }
            ]
        }
        content = json.dumps(payload, ensure_ascii=False)
        return LLMResult(
            content=content,
            parsed_json=payload,
            input_tokens=10,
            output_tokens=5,
            input_cost_usd=0.0,
            output_cost_usd=0.0,
            total_cost_usd=0.0,
        )

    monkeypatch.setattr(LLMClient, "summarize_text", _bogus)
    with session_scope() as session:
        paper_id = _mk_paper(session)
        stats = ClaimExtractionService().extract_in_session(
            session, paper_id, source_text=SOURCE_TEXT
        )
        assert stats["claims_created"] == 1
        assert stats["claims_unverified"] == 1
        claim = session.execute(
            select(Claim).where(Claim.origin == ClaimOrigin.papermind)
        ).scalar_one()
        # 引用不可核实 → 保持 draft（无证据），绝不伪造坐标
        assert claim.status is ClaimStatus.draft
        assert (
            session.execute(
                select(func.count()).select_from(Evidence).where(Evidence.claim_id == claim.id)
            ).scalar()
            == 0
        )
        run = session.get(ResearchRun, stats["run_id"])
        assert run.status is ResearchRunStatus.partial


def test_extraction_requires_text(isolated_db, fake_llm):
    with session_scope() as session:
        paper_id = _mk_paper(session, abstract="")
        with pytest.raises(ValidationError):
            ClaimExtractionService().extract_in_session(session, paper_id)
