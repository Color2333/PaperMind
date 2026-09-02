"""Research State 垂直切片样本种子（A4/D2，设计① §9 迁移策略）

对一个预置 ResearchQuestion 构造最小可验证样本：

- 选取少量论文（显式 arxiv_ids，或缺省取最近已 skim 的 3 篇），补建 v1
  SourceVersion——仅限本切片论文，不批量回填历史数据。
- 每篇从摘要提取一条 author 判断（引用即证：quote=摘要原句、locator=abstract），
  按 D1 已确认的规则自动 confirmed。
- 一条 papermind 综合判断保持 draft（等待人工校验；D3 的真实 ResearchRun
  会替代这种占位综合）。
- author 判断 → 综合判断之间记录 supports 关系（断言来源 papermind）。
- 幂等：重复执行不产生重复 question/版本/判断/证据/关系。

application 层（Stage B）建立后，此函数应迁为 SeedResearchSample command。
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import TYPE_CHECKING

from sqlalchemy import select

from packages.domain.enums import (
    ClaimOrigin,
    EvidenceKind,
    EvidenceStance,
    RelationOrigin,
    RelationPredicate,
    RunTrigger,
    SourceDetectedBy,
)
from packages.storage.models import Claim, Paper
from packages.storage.repositories import (
    ClaimRelationRepository,
    ClaimRepository,
    ResearchQuestionRepository,
    ResearchRunRepository,
    SourceVersionRepository,
)

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

QUESTION_TITLE = "视听说话人分离（audio-visual diarization）"
QUESTION_TEXT = (
    "在多说话人场景下，哪些视听结合的说话人分离方法当前最有效？其证据强度与适用条件如何？"
)
DEFAULT_PAPERS_LIMIT = 3


def _first_sentence(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    for sep in (". ", "。"):
        idx = text.find(sep)
        if idx > 0:
            return text[: idx + 1].strip()
    return text[:200]


def _identity_hash(paper: Paper) -> str:
    identity = json.dumps(
        {"abstract": paper.abstract, "arxiv_id": paper.arxiv_id, "title": paper.title},
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _select_papers(session: Session, arxiv_ids: list[str] | None) -> list[Paper]:
    if arxiv_ids:
        papers: list[Paper] = []
        for arxiv_id in arxiv_ids:
            paper = session.execute(
                select(Paper).where(Paper.arxiv_id == arxiv_id)
            ).scalar_one_or_none()
            if paper is None:
                raise ValueError(f"论文不存在：arxiv_id={arxiv_id}")
            papers.append(paper)
        return papers
    return list(
        session.execute(
            select(Paper)
            .where(Paper.read_status.in_(["skimmed", "deep_read"]))
            .order_by(Paper.created_at.desc())
            .limit(DEFAULT_PAPERS_LIMIT)
        ).scalars()
    )


def seed_sample(
    session: Session,
    *,
    arxiv_ids: list[str] | None = None,
    dry_run: bool = False,
) -> dict:
    """构建/补齐预置研究问题样本，返回统计；重复执行等价于 no-op。"""
    papers = _select_papers(session, arxiv_ids)
    entries: list[tuple[Paper, str]] = []
    for paper in papers:
        sentence = _first_sentence(paper.abstract)
        if sentence:
            entries.append((paper, sentence))
    if not entries:
        raise ValueError("没有可用的切片论文：请先 skim 少量论文，或用 --arxiv-id 指定带摘要的论文")

    plan = {
        "question_id": None,
        "papers_selected": [p.arxiv_id for p, _ in entries],
        "versions_to_create": 0,
        "claims_to_create": 0,
        "dry_run": dry_run,
    }
    sv_repo = SourceVersionRepository(session)
    plan["versions_to_create"] = sum(1 for p, _ in entries if sv_repo.get_current(p.id) is None)
    if dry_run:
        return plan

    q_repo = ResearchQuestionRepository(session)
    question = next((q for q in q_repo.list_active() if q.title == QUESTION_TITLE), None)
    if question is None:
        question = q_repo.create(title=QUESTION_TITLE, question=QUESTION_TEXT)
    plan["question_id"] = question.id

    claim_repo = ClaimRepository(session)
    stats = {
        "question_id": question.id,
        "papers_selected": plan["papers_selected"],
        "versions_created": 0,
        "author_claims_created": 0,
        "author_claims_existing": 0,
        "evidence_created": 0,
        "meta_claim_created": 0,
        "relations_created": 0,
    }

    author_claims = []
    for paper, sentence in entries:
        if sv_repo.get_current(paper.id) is None:
            sv_repo.create_for_paper(
                paper.id,
                content_hash=_identity_hash(paper),
                detected_by=SourceDetectedBy.ingest,
            )
            stats["versions_created"] += 1
        existing_claim = session.execute(
            select(Claim).where(
                Claim.research_question_id == question.id,
                Claim.statement == sentence,
                Claim.origin == ClaimOrigin.author,
            )
        ).scalar_one_or_none()
        if existing_claim is None:
            claim = claim_repo.create(
                statement=sentence,
                origin=ClaimOrigin.author,
                research_question_id=question.id,
            )
            stats["author_claims_created"] += 1
        else:
            claim = existing_claim
            stats["author_claims_existing"] += 1
        author_claims.append(claim)
        _, evidence_created = claim_repo.add_evidence(
            claim.id,
            source_version_id=sv_repo.get_current(paper.id).id,
            kind=EvidenceKind.text_passage,
            stance=EvidenceStance.supports,
            locator={"section": "abstract"},
            quote=sentence,
            extracted_by=ClaimOrigin.author,
        )
        if evidence_created:
            stats["evidence_created"] += 1

    # papermind 综合判断（draft：明确等待人工校验，不冒充事实）
    meta_statement = (
        f"综合判断（待人工校验）：上述 {len(author_claims)} 条作者结论方向一致，"
        "可联合支撑该问题的当前研究状态。"
    )
    meta_claim = session.execute(
        select(Claim).where(
            Claim.research_question_id == question.id,
            Claim.statement == meta_statement,
            Claim.origin == ClaimOrigin.papermind,
        )
    ).scalar_one_or_none()
    relation_repo = ClaimRelationRepository(session)
    if meta_claim is None:
        run = ResearchRunRepository(session).start(
            kind="seed_sample",
            research_question_id=question.id,
            paper_ids=[p.id for p, _ in entries],
            trigger=RunTrigger.manual,
        )
        meta_claim = claim_repo.create(
            statement=meta_statement,
            origin=ClaimOrigin.papermind,
            research_question_id=question.id,
            run_id=run.id,
        )
        stats["meta_claim_created"] = 1
        for author_claim in author_claims:
            _, relation_created = relation_repo.record(
                subject_claim_id=author_claim.id,
                object_claim_id=meta_claim.id,
                predicate=RelationPredicate.supports,
                origin=RelationOrigin.papermind,
                run_id=run.id,
            )
            if relation_created:
                stats["relations_created"] += 1

    stats["meta_claim_id"] = meta_claim.id
    logger.info("research seed 完成：%s", stats)
    return stats
