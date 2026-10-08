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


def apply_ingest_papers_proposal(session: Session, proposal: dict) -> dict:
    """应用批量入库 proposal：papers upsert（arxiv_id 幂等 + skim 保护合并）+
    topic 解析/自动创建 + paper_topics 关联 + collection_actions。

    与 Go applyIngestPapersResult 语义对齐。差异（有意修正）：topic_subscriptions
    已存在时不再改写 enabled（Python 旧路径会把用户已启用订阅禁掉）。
    """
    from datetime import date as _date

    from sqlalchemy import select

    from packages.domain.enums import ActionType
    from packages.domain.schemas import PaperCreate
    from packages.storage.models import Paper, TopicSubscription
    from packages.storage.repositories import ActionRepository, PaperRepository

    query = str(proposal.get("query") or "")
    papers = proposal.get("papers") or []
    if not papers:
        # 空 = 合法 no-op（重复摄入全部命中已存在）
        return {"total": 0, "inserted_ids": [], "topic_id": proposal.get("topic_id")}

    # topic 解析：显式 topic_id > topic_name 自动创建（不存在时，enabled=False）
    topic_id = proposal.get("topic_id") or None
    topic_name = (proposal.get("topic_name") or "").strip() or None
    if topic_id is None and topic_name:
        found = session.execute(
            select(TopicSubscription).where(TopicSubscription.name == topic_name)
        ).scalar_one_or_none()
        if found is None:
            found = TopicSubscription(name=topic_name, query=topic_name, enabled=False)
            session.add(found)
            session.flush()
        topic_id = str(found.id)

    repo = PaperRepository(session)
    inserted_ids: list[str] = []
    for item in papers:
        pub = item.get("publication_date")
        repo.upsert_paper(
            PaperCreate(
                arxiv_id=str(item.get("arxiv_id") or ""),
                title=str(item.get("title") or f"arXiv:{item.get('arxiv_id')}"),
                abstract=str(item.get("abstract") or ""),
                publication_date=_date.fromisoformat(pub) if isinstance(pub, str) else pub,
                metadata=item.get("metadata") or {},
                source=item.get("source") or "arxiv",
                source_id=item.get("source_id"),
                doi=item.get("doi") or None,
            )
        )
        paper_row = session.execute(
            select(Paper).where(Paper.arxiv_id == item.get("arxiv_id"))
        ).scalar_one()
        inserted_ids.append(str(paper_row.id))
        if topic_id:
            repo.link_to_topic(str(paper_row.id), str(topic_id))

    action_type = str(proposal.get("action_type") or "manual_collect")
    ActionRepository(session).create_action(
        action_type=ActionType(action_type),
        title=str(proposal.get("action_title") or query[:80]),
        paper_ids=inserted_ids,
        query=query,
        topic_id=topic_id,
    )
    return {
        "total": len(inserted_ids),
        # 与 Go applyIngestPapersResult 对齐：不截断（主题摄取编排器依赖
        # inserted_ids 提交下游 skim/embed；上限由 max_results 约束）
        "inserted_ids": inserted_ids,
        "topic_id": topic_id,
    }


def apply_cs_feed_fetch_proposal(session: Session, proposal: dict) -> dict:
    """应用 CS 分类抓取 proposal：papers upsert + csfeed:{code} 主题关联
    （自动创建 enabled=False）+ 订阅运行状态（last_run_at/count 跨天清零累加）。

    与 Go applyCsFeedFetchResult 语义对齐。"""
    from datetime import date as _date

    from sqlalchemy import select

    from packages.domain.schemas import PaperCreate
    from packages.storage.models import Paper, TopicSubscription
    from packages.storage.repositories import CSFeedRepository, PaperRepository

    category_code = str(proposal.get("category_code") or "")
    papers = proposal.get("papers") or []
    if not category_code:
        raise ValueError("cs_feed_fetch proposal 缺少 category_code")

    topic_name = f"csfeed:{category_code}"
    found = session.execute(
        select(TopicSubscription).where(TopicSubscription.name == topic_name)
    ).scalar_one_or_none()
    if found is None:
        found = TopicSubscription(name=topic_name, query=f"cat:{category_code}", enabled=False)
        session.add(found)
        session.flush()
    topic_id = str(found.id)

    repo = PaperRepository(session)
    inserted_ids: list[str] = []
    for item in papers:
        pub = item.get("publication_date")
        repo.upsert_paper(
            PaperCreate(
                arxiv_id=str(item.get("arxiv_id") or ""),
                title=str(item.get("title") or f"arXiv:{item.get('arxiv_id')}"),
                abstract=str(item.get("abstract") or ""),
                publication_date=_date.fromisoformat(pub) if isinstance(pub, str) else pub,
                metadata=item.get("metadata") or {},
                source=item.get("source") or "arxiv",
                source_id=item.get("source_id"),
                doi=item.get("doi") or None,
            )
        )
        paper_row = session.execute(
            select(Paper).where(Paper.arxiv_id == item.get("arxiv_id"))
        ).scalar_one()
        inserted_ids.append(str(paper_row.id))
        repo.link_to_topic(str(paper_row.id), topic_id)

    # 订阅运行状态：当日累加、跨天清零（与 CSFeedRepository.update_run_status 一致）
    fetched = len(papers)
    CSFeedRepository(session).update_run_status(category_code, fetched)
    return {
        "total": len(inserted_ids),
        "inserted_ids": inserted_ids,
        "category_code": category_code,
        "topic_id": topic_id,
        "fetched": fetched,
    }


def apply_cs_categories_sync_proposal(session: Session, proposal: dict) -> dict:
    """应用 CS 分类同步 proposal：cs_categories upsert（code 主键幂等）。

    与 Go applyCsCategoriesSyncResult 语义对齐。"""
    from packages.storage.repositories import CSFeedRepository

    cats = proposal.get("categories") or []
    repo = CSFeedRepository(session)
    for c in cats:
        code = str(c.get("code") or "").strip()
        if not code:
            continue
        repo.upsert_category(code, str(c.get("name") or ""), str(c.get("description") or ""))
    return {"synced": len(cats)}


def apply_save_generated_content_proposal(session: Session, proposal: dict) -> dict:
    """应用生成内容 proposal：generated_contents 插入（与 Go 语义对齐）"""
    from packages.storage.repositories import GeneratedContentRepository

    content_type = str(proposal.get("content_type") or "")
    title = str(proposal.get("title") or "")
    if not content_type or not title:
        raise ValueError("save_generated_content proposal 缺少 content_type/title")
    gc = GeneratedContentRepository(session).create(
        content_type=content_type,
        title=title,
        markdown=str(proposal.get("markdown") or ""),
        keyword=proposal.get("keyword"),
        paper_id=proposal.get("paper_id"),
        metadata_json=proposal.get("metadata_json") or {},
    )
    return {"content_id": str(gc.id), "content_type": content_type}


def apply_citation_edges_proposal(session: Session, proposal: dict) -> dict:
    """引用边批量入库（与 Go applyCitationEdgesResult 语义对齐）"""
    from packages.ai.graph._common import _title_to_id
    from packages.domain.schemas import PaperCreate
    from packages.storage.repositories import CitationRepository, PaperRepository

    repo = PaperRepository(session)
    cit_repo = CitationRepository(session)
    inserted = 0
    for e in proposal.get("edges") or []:
        src = repo.upsert_paper(
            PaperCreate(
                arxiv_id=e["source"].get("arxiv_id") or _title_to_id(e["source"].get("title", "")),
                title=e["source"].get("title") or "",
                abstract=e["source"].get("abstract") or "",
                metadata=e["source"].get("metadata") or {},
            )
        )
        dst = repo.upsert_paper(
            PaperCreate(
                arxiv_id=e["target"].get("arxiv_id") or _title_to_id(e["target"].get("title", "")),
                title=e["target"].get("title") or "",
                abstract=e["target"].get("abstract") or "",
                metadata=e["target"].get("metadata") or {},
            )
        )
        if cit_repo.upsert_edge(str(src.id), str(dst.id), context=e.get("context")):
            inserted += 1
    return {"edges_inserted": inserted}


def apply_figure_analyses_proposal(session: Session, proposal: dict) -> dict:
    """image_analyses 删重建（与 Go/Python _save_analyses 语义一致）"""
    from sqlalchemy import delete

    from packages.storage.models import ImageAnalysis

    paper_id = str(proposal.get("paper_id") or "")
    if not paper_id:
        raise ValueError("figure_analyses proposal 缺少 paper_id")
    # 先 flush（把同 session 内 pending 的前批写入），再删重建——bulk delete 用
    # fetch 同步从 identity map 移除，避免会话内新旧两批叠加
    session.flush()
    session.execute(
        delete(ImageAnalysis)
        .where(ImageAnalysis.paper_id == paper_id)
        .execution_options(synchronize_session="fetch")
    )
    for a in proposal.get("analyses") or []:
        session.add(
            ImageAnalysis(
                paper_id=paper_id,
                page_number=int(a.get("page_number") or 0),
                image_index=int(a.get("image_index") or 0),
                image_type=str(a.get("image_type") or "figure"),
                caption=a.get("caption"),
                description=str(a.get("description") or ""),
                image_path=a.get("image_path"),
                bbox_json=a.get("bbox_json") or {},
            )
        )
    return {"count": len(proposal.get("analyses") or [])}


def apply_paper_translation_proposal(session: Session, proposal: dict) -> dict:
    """paper_translations upsert（paper_id+lang+mode 唯一）"""
    from sqlalchemy import select

    from packages.storage.models import PaperTranslation

    paper_id = str(proposal.get("paper_id") or "")
    target_lang = str(proposal.get("target_lang") or "")
    mode = str(proposal.get("mode") or "")
    if not paper_id or not target_lang or not mode:
        raise ValueError("paper_translation proposal 缺少键")
    session.flush()  # 同 session 内 pending 的前批先落库，保证 upsert 查得到
    existing = session.execute(
        select(PaperTranslation).where(
            PaperTranslation.paper_id == paper_id,
            PaperTranslation.target_lang == target_lang,
            PaperTranslation.mode == mode,
        )
    ).scalar_one_or_none()
    if existing is None:
        existing = PaperTranslation(paper_id=paper_id, target_lang=target_lang, mode=mode)
        session.add(existing)
    if proposal.get("segments") is not None:
        existing.segments = proposal["segments"]
    if proposal.get("bilingual_pdf_path"):
        existing.bilingual_pdf_path = proposal["bilingual_pdf_path"]
    return {"paper_id": paper_id, "target_lang": target_lang, "mode": mode}


def apply_reference_import_proposal(session: Session, proposal: dict) -> dict:
    """参考文献导入（与 Go applyReferenceImportResult 语义对齐）"""
    from sqlalchemy import select

    from packages.domain.enums import ActionType
    from packages.domain.schemas import PaperCreate
    from packages.storage.models import Paper
    from packages.storage.repositories import (
        ActionRepository,
        CitationRepository,
        PaperRepository,
    )

    source_paper_id = str(proposal.get("source_paper_id") or "")
    source_title = str(proposal.get("source_paper_title") or "")
    if not source_paper_id:
        raise ValueError("reference_import proposal 缺少 source_paper_id")

    repo = PaperRepository(session)
    cit_repo = CitationRepository(session)
    inserted_ids: list[str] = []
    for item in proposal.get("papers") or []:
        pd = item.get("paper") or {}
        paper = repo.upsert_paper(
            PaperCreate(
                arxiv_id=pd.get("arxiv_id") or None,
                title=pd.get("title") or "",
                abstract=pd.get("abstract") or "",
                metadata=pd.get("metadata") or {},
            )
        )
        inserted_ids.append(str(paper.id))
        for tid in item.get("topics") or []:
            repo.link_to_topic(str(paper.id), str(tid))
        direction = item.get("direction") or "reference"
        if direction == "reference":
            cit_repo.upsert_edge(source_paper_id, str(paper.id), context="reference")
        else:
            cit_repo.upsert_edge(str(paper.id), source_paper_id, context="citation")
        # 修正 upsert 后的 arxiv_id 精确性（PaperCreate 空 arxiv_id 时合成 id）
        _ = session.execute(select(Paper).where(Paper.id == paper.id)).scalar_one()

    if inserted_ids:
        ActionRepository(session).create_action(
            action_type=ActionType.reference_import,
            title=f"参考文献导入：{source_title[:60]}",
            paper_ids=inserted_ids,
            query=source_paper_id,
        )
    return {"inserted_ids": inserted_ids[:20], "total": len(inserted_ids)}


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
    if kind == "ingest_papers":
        return apply_ingest_papers_proposal(session, proposal)
    if kind == "cs_feed_fetch":
        return apply_cs_feed_fetch_proposal(session, proposal)
    if kind == "cs_categories_sync":
        return apply_cs_categories_sync_proposal(session, proposal)
    if kind == "save_generated_content":
        return apply_save_generated_content_proposal(session, proposal)
    if kind == "citation_edges":
        return apply_citation_edges_proposal(session, proposal)
    if kind == "figure_analyses":
        return apply_figure_analyses_proposal(session, proposal)
    if kind == "paper_translation":
        return apply_paper_translation_proposal(session, proposal)
    if kind == "reference_import":
        return apply_reference_import_proposal(session, proposal)
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
