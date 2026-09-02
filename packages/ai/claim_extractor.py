"""Claim 抽取服务（D3）：一次 ResearchRun 生成待验证 Claim

Phase 3 的核心链路：deep read 产出的文本 → LLM 抽取带精确引用与定位坐标的判断 →
papermind origin 的 Claim（draft/pending_verification）+ Evidence（挂当前
SourceVersion）+ ResearchRun/PromptTrace provenance。

extract_in_session 在调用方事务内执行（deep_dive 用它保证 Run/Claim/Artifact
原子提交）；extract_for_paper 是自带事务的独立入口（CLI/MCP/application 调用）。

硬规则（设计① §5）：
- 引用无法在源文本中核实 → Claim 保持 draft（无证据），绝不伪造坐标；
- 引用可核实 → draft + 坐标完整证据 → 仓储规则推进到 pending_verification；
- papermind 判断永远不能自动 confirmed（由 ClaimRepository 强制）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import time

from sqlalchemy import select

from packages.ai.prompts import build_claim_extraction_prompt
from packages.config import get_settings
from packages.domain.enums import (
    ClaimCertainty,
    ClaimOrigin,
    EvidenceKind,
    EvidenceStance,
    ResearchRunStatus,
    RunTrigger,
    SourceDetectedBy,
)
from packages.domain.exceptions import ValidationError
from packages.integrations.llm_client import LLMClient
from packages.storage.models import Evidence, Paper, PromptTrace
from packages.storage.repositories import (
    ClaimRepository,
    PaperRepository,
    ResearchRunRepository,
    SourceVersionRepository,
)

logger = logging.getLogger(__name__)

_MAX_CLAIMS = 6


def _identity_hash(paper: Paper) -> str:
    identity = json.dumps(
        {"abstract": paper.abstract, "arxiv_id": paper.arxiv_id, "title": paper.title},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _parse_certainty(raw: object) -> ClaimCertainty | None:
    if not raw:
        return None
    try:
        return ClaimCertainty(str(raw))
    except ValueError:
        return None


def _evidence_exists(session, source_version_id: str, locator: dict, quote: str) -> bool:
    """幂等键：同版本 + 同引用 + 同坐标 → 该判断已抽取过"""
    if not quote:
        return False
    rows = (
        session.execute(
            select(Evidence).where(
                Evidence.source_version_id == source_version_id,
                Evidence.quote == quote,
            )
        )
        .scalars()
        .all()
    )
    return any((row.locator or {}) == (locator or {}) for row in rows)


class ClaimExtractionService:
    def __init__(self) -> None:
        self.llm = LLMClient()

    def extract_for_paper(
        self,
        paper_id: str,
        *,
        source_text: str | None = None,
        research_question_id: str | None = None,
    ) -> dict:
        """独立入口：自带事务。"""
        from packages.storage.db import session_scope

        with session_scope() as session:
            return self.extract_in_session(
                session,
                paper_id,
                source_text=source_text,
                research_question_id=research_question_id,
            )

    def extract_in_session(
        self,
        session,
        paper_id: str,
        *,
        source_text: str | None = None,
        research_question_id: str | None = None,
    ) -> dict:
        """在调用方事务内执行——deep_dive 等管线用它保证原子提交"""
        started = time.perf_counter()
        paper = PaperRepository(session).get_by_id(paper_id)
        text = (source_text or paper.abstract or "").strip()
        if not text:
            raise ValidationError(f"论文 {paper_id} 没有可抽取的文本")

        run_repo = ResearchRunRepository(session)
        run = run_repo.start(
            kind="claim_extraction",
            research_question_id=research_question_id,
            paper_ids=[str(paper.id)],
            trigger=RunTrigger.api,
            model_policy={
                "provider": self.llm.provider,
                "model": get_settings().llm_model_deep,
                "policy_version": "claim-extraction-v1",
            },
        )

        prompt = build_claim_extraction_prompt(paper.title, text)
        result = self.llm.complete_json(prompt, stage="claim_extraction")

        # 成本 provenance：直接构造 PromptTrace 以拿到 id（repo.create 不返回对象）
        trace = PromptTrace(
            stage="claim_extraction",
            provider=self.llm.provider,
            model=get_settings().llm_model_deep,
            prompt_digest=prompt[:500],
            paper_id=str(paper.id),
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            input_cost_usd=result.input_cost_usd,
            output_cost_usd=result.output_cost_usd,
            total_cost_usd=result.total_cost_usd,
        )
        session.add(trace)
        session.flush()

        sv_repo = SourceVersionRepository(session)
        sv = sv_repo.get_current(str(paper.id))
        if sv is None:
            # 仅在本切片"触碰"该论文时回补 v1（设计① §9：不批量回填历史）
            sv = sv_repo.create_for_paper(
                str(paper.id),
                content_hash=_identity_hash(paper),
                doi=paper.doi,
                detected_by=SourceDetectedBy.ingest,
            )

        claim_repo = ClaimRepository(session)
        stats = {
            "run_id": run.id,
            "claims_created": 0,
            "claims_unverified": 0,
            "claims_skipped": 0,
        }
        items = (result.parsed_json or {}).get("claims") or []
        for item in items[:_MAX_CLAIMS]:
            if not isinstance(item, dict):
                continue
            statement = str(item.get("statement") or "").strip()
            if not statement:
                continue
            quote = str(item.get("quote") or "").strip()
            locator_raw = item.get("locator")
            locator = dict(locator_raw) if isinstance(locator_raw, dict) else {}
            if _evidence_exists(session, str(sv.id), locator, quote):
                stats["claims_skipped"] += 1
                continue
            claim = claim_repo.create(
                statement=statement,
                origin=ClaimOrigin.papermind,
                research_question_id=research_question_id,
                statement_zh=str(item.get("statement_zh") or "").strip() or None,
                certainty=_parse_certainty(item.get("certainty")),
                run_id=run.id,
            )
            stats["claims_created"] += 1
            if quote and locator and quote.lower() in text.lower():
                claim_repo.add_evidence(
                    claim.id,
                    source_version_id=str(sv.id),
                    kind=EvidenceKind.text_passage,
                    stance=EvidenceStance.supports,
                    locator=locator,
                    quote=quote,
                    extracted_by=ClaimOrigin.papermind,
                    run_id=run.id,
                )
            else:
                # 引用不可核实 → 保持 draft（无证据），等待人工补充，绝不伪造坐标
                stats["claims_unverified"] += 1

        run_repo.complete(
            run.id,
            status=(
                ResearchRunStatus.partial
                if stats["claims_unverified"]
                else ResearchRunStatus.succeeded
            ),
            cost_refs=[str(trace.id)],
            artifact_refs={
                "claims_created": stats["claims_created"],
                "claims_unverified": stats["claims_unverified"],
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
            },
        )
        return stats
