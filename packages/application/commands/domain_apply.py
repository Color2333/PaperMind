"""领域结果应用（第三轮 REVIEW P0-1：proposal 与 Task 终态同事务提交）

每个 capability 的 apply 函数接收已通过 fencing 校验的 proposal，
在调用方的**同一事务/session** 内提交领域变化。Executor 不再直写领域表——
Python authority 路径：durable-state /complete 在 complete_task 的同一
session 中调用本模块；Go authority 路径：core 以 SQL 在单事务内实现同等语义。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def apply_skim_proposal(session: Session, proposal: dict) -> None:
    """应用 skim proposal：analysis_reports upsert + papers 状态/metadata。

    与 Go Core apply-result 的 SQL 语义逐字段对齐（见 core/apply_result.go）。
    """
    from packages.domain.enums import ReadStatus
    from packages.storage.repositories import AnalysisRepository, PaperRepository

    skim = proposal.get("skim") or {}
    paper_id = proposal.get("paper_id")
    if not paper_id or not skim:
        raise ValueError("skim proposal 缺少 paper_id/skim 字段")

    paper_repo = PaperRepository(session)
    paper = paper_repo.get_by_id(paper_id)

    from packages.domain.schemas import SkimReport

    report = SkimReport.model_validate(skim)
    AnalysisRepository(session).upsert_skim(paper.id, report)

    meta = dict(paper.metadata_json or {})
    if report.keywords:
        meta["keywords"] = report.keywords
    if report.title_zh:
        meta["title_zh"] = report.title_zh
    if report.abstract_zh:
        meta["abstract_zh"] = report.abstract_zh
    paper.metadata_json = meta
    paper_repo.update_read_status(paper.id, ReadStatus.skimmed)


def apply_deep_read_proposal(session: Session, proposal: dict) -> None:
    """应用 deep read proposal：deep_dive_md + read_status 只升不降。

    与 Go applyDeepReadResult 逐字段对齐。inline claim 抽取由独立
    extract_claims 任务承载（proposal 模式下不在此处执行）。
    """
    from packages.domain.enums import ReadStatus
    from packages.domain.schemas import DeepDiveReport
    from packages.storage.repositories import AnalysisRepository, PaperRepository

    deep = proposal.get("deep") or {}
    paper_id = proposal.get("paper_id")
    if not paper_id or not deep:
        raise ValueError("deep proposal 缺少 paper_id/deep 字段")

    paper_repo = PaperRepository(session)
    paper = paper_repo.get_by_id(paper_id)
    report = DeepDiveReport.model_validate(deep)
    AnalysisRepository(session).upsert_deep_dive(paper.id, report)
    # 只升不降（unread→skimmed→deep_read）
    paper_repo.update_read_status(paper.id, ReadStatus.deep_read)


def apply_embed_proposal(session: Session, proposal: dict) -> None:
    """应用 embed proposal：papers.embedding 向量写入"""
    from packages.storage.repositories import PaperRepository  # noqa: TC001 —— 运行时需要

    vector = proposal.get("vector")
    paper_id = proposal.get("paper_id")
    if not paper_id or vector is None:
        raise ValueError("embed proposal 缺少 paper_id/vector 字段")

    PaperRepository(session).update_embedding(paper_id, vector)


def apply_extract_claims_proposal(session: Session, proposal: dict) -> dict:
    """应用 claim 抽取 proposal：ResearchRun + claims + evidence（指纹去重）。

    指纹去重逻辑在 Python（_evidence_exists/claim_repo.create）——此 capability
    的领域 apply 留在 Python authority（extract_claims 不路由 Go，见
    GO_OWNED_CAPABILITIES）；同事务保证 fencing+终态+领域变化原子性。
    """
    from packages.ai.claim_extractor import (
        _MAX_CLAIMS,
        _evidence_exists,
        _identity_hash,
        _parse_certainty,
    )
    from packages.domain.enums import (
        ClaimOrigin,
        EvidenceKind,
        EvidenceStance,
        RunTrigger,
        SourceDetectedBy,
    )
    from packages.storage.models import PromptTrace
    from packages.storage.repositories import (
        ClaimRepository,
        PaperRepository,
        ResearchRunRepository,
        SourceVersionRepository,
    )

    items = proposal.get("items") or []
    trace = proposal.get("trace") or {}
    run_meta = proposal.get("run_meta") or {}
    paper_id = proposal.get("paper_id")
    if not paper_id:
        raise ValueError("extract_claims proposal 缺少 paper_id")

    paper = PaperRepository(session).get_by_id(paper_id)
    # 原文不随 proposal 携带（体积）；pending_verification 判定由抽取器创建时状态兜底
    run_repo = ResearchRunRepository(session)
    run = run_repo.start(
        kind="claim_extraction",
        paper_ids=[str(paper.id)],
        trigger=RunTrigger.api,
        model_policy=run_meta.get("model_policy") or {},
    )

    trace_row = PromptTrace(
        stage=trace.get("stage", "claim_extraction"),
        provider=trace.get("provider", "unknown"),
        model=trace.get("model", "unknown"),
        prompt_digest=trace.get("prompt_digest", ""),
        paper_id=str(paper.id),
        input_tokens=trace.get("input_tokens"),
        output_tokens=trace.get("output_tokens"),
        input_cost_usd=trace.get("input_cost_usd"),
        output_cost_usd=trace.get("output_cost_usd"),
        total_cost_usd=trace.get("total_cost_usd"),
    )
    session.add(trace_row)
    session.flush()

    sv_repo = SourceVersionRepository(session)
    sv = sv_repo.get_current(str(paper.id))
    if sv is None:
        sv = sv_repo.create_for_paper(
            str(paper.id),
            content_hash=_identity_hash(paper),
            doi=paper.doi,
            detected_by=SourceDetectedBy.ingest,
        )

    claim_repo = ClaimRepository(session)
    stats = {"claims_created": 0, "claims_skipped": 0}
    for item in items[:_MAX_CLAIMS]:
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
            statement_zh=str(item.get("statement_zh") or "").strip() or None,
            certainty=_parse_certainty(item.get("certainty")),
            run_id=run.id,
        )
        stats["claims_created"] += 1
        if quote and locator:
            claim_repo.add_evidence(
                claim.id,
                source_version_id=str(sv.id),
                kind=EvidenceKind.text_passage,
                stance=EvidenceStance.supports,
                quote=quote,
                locator=locator,
            )
            claim.statement_zh = str(item.get("statement_zh") or "").strip() or claim.statement_zh
            # pending_verification 由 claim 卫生规则（引用可核实）在抽取时判定——
            # proposal 模式无原文文本，保持创建默认状态

    run_repo.complete(run.id, cost_refs=[])
    return stats


def apply_upsert_proposal(session: Session, proposal: dict) -> dict:
    """应用论文 upsert proposal：papers 行 upsert（arxiv_id 幂等 + metadata 合并）。

    与 Go applyUpsertPaperResult 语义对齐（source_versions v1 由 Go 侧承载；
    Python authority 路径保持 handler 时代的 upsert_paper 语义）。
    """
    from packages.domain.schemas import PaperCreate
    from packages.storage.repositories import PaperRepository

    arxiv_id = str(proposal.get("arxiv_id") or "").strip()
    if not arxiv_id:
        raise ValueError("upsert proposal 缺少 arxiv_id")
    paper = PaperRepository(session).upsert_paper(
        PaperCreate(
            arxiv_id=arxiv_id,
            title=str(proposal.get("title") or f"arXiv:{arxiv_id}"),
            abstract=str(proposal.get("abstract") or ""),
            metadata=proposal.get("metadata") or {},
        )
    )
    return {"paper_id": str(paper.id), "arxiv_id": arxiv_id}


def apply_download_proposal(session: Session, proposal: dict) -> dict:
    """应用 PDF 下载 proposal：papers.pdf_path 回填（文件下载 IO 在 handler 完成）"""
    from sqlalchemy import select

    from packages.storage.models import Paper
    from packages.storage.repositories import PaperRepository

    arxiv_id = str(proposal.get("arxiv_id") or "").strip()
    pdf_path = str(proposal.get("pdf_path") or proposal.get("pdf_url") or "").strip()
    if not arxiv_id or not pdf_path:
        raise ValueError("download proposal 缺少 arxiv_id/pdf_path")
    paper = session.execute(select(Paper).where(Paper.arxiv_id == arxiv_id)).scalar_one_or_none()
    if paper is None:
        raise ValueError(f"论文 {arxiv_id} 不在库中（upsert 应先行）")
    PaperRepository(session).set_pdf_path(paper.id, pdf_path)
    return {"arxiv_id": arxiv_id, "pdf_path": pdf_path}


def apply_proposal(session: Session, proposal: dict) -> dict | None:
    """proposal 分派（唯一实现，三条路径共用）：
    - Go authority：core ApplyResult 按 capability SQL 直写（A 档）；
    - Python authority：durable-state /complete 在终态同事务调用本函数；
    - 测试执行器复用同语义（此前分派被复制在测试 helper——收敛到此）。

    返回 stored_ref（/tasks/{id}/result 消费者契约）；未知 kind 返回 None
    （B 档：领域写入由 handler 承载，result 原样存储）。
    """
    kind = proposal.get("kind")
    if kind == "skim_paper":
        apply_skim_proposal(session, proposal)
        apply_prompt_trace(session, proposal)
        return proposal.get("skim") or {"kind": kind}
    if kind == "deep_read_paper":
        apply_deep_read_proposal(session, proposal)
        apply_prompt_trace(session, proposal)
        return proposal.get("deep") or {"kind": kind}
    if kind == "embed_paper":
        apply_embed_proposal(session, proposal)
        return {"embedded": True}
    if kind == "extract_claims":
        stats = apply_extract_claims_proposal(session, proposal)
        apply_prompt_trace(session, proposal)
        return stats or {"kind": kind}
    if kind == "upsert_paper":
        return apply_upsert_proposal(session, proposal)
    if kind == "download_source":
        return apply_download_proposal(session, proposal)
    return None


def apply_prompt_trace(session: Session, proposal: dict) -> None:
    """应用 prompt trace（成本观测行；随领域变化同事务写入）"""
    from packages.storage.repositories import PromptTraceRepository

    trace = dict(proposal.get("trace") or {})
    if not trace:
        return
    trace.setdefault("paper_id", proposal.get("paper_id"))
    PromptTraceRepository(session).create(
        stage=trace.get("stage", "unknown"),
        provider=trace.get("provider", "unknown"),
        model=trace.get("model", "unknown"),
        prompt_digest=trace.get("prompt_digest", ""),
        paper_id=trace.get("paper_id"),
        input_tokens=trace.get("input_tokens"),
        output_tokens=trace.get("output_tokens"),
        input_cost_usd=trace.get("input_cost_usd"),
        output_cost_usd=trace.get("output_cost_usd"),
        total_cost_usd=trace.get("total_cost_usd"),
    )
