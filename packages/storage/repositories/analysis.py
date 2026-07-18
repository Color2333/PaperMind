"""
分析报告数据仓储
@author Color2333
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.orm import Session

    from packages.domain.schemas import DeepDiveReport, SkimReport

from packages.storage.models import AnalysisReport


class AnalysisRepository:
    def __init__(self, session: Session):
        self.session = session

    def upsert_skim(self, paper_id: UUID, skim: SkimReport) -> None:
        report = self._get_or_create(paper_id)
        innovations = "".join([f"  - {x}\n" for x in skim.innovations])
        report.summary_md = f"- 一句话: {skim.one_liner}\n- 创新点:\n{innovations}"
        report.skim_score = skim.relevance_score
        # key_insights 同时存 innovations 和 one_liner：
        # one_liner 干净存一份，避免下游（如 embed_paper）解析 summary_md
        report.key_insights = {
            "skim_innovations": skim.innovations,
            "skim_one_liner": skim.one_liner,
        }

    def upsert_deep_dive(self, paper_id: UUID, deep: DeepDiveReport) -> None:
        report = self._get_or_create(paper_id)
        risks = "".join([f"- {x}\n" for x in deep.reviewer_risks])
        report.deep_dive_md = (
            f"## Method\n{deep.method_summary}\n\n"
            f"## Experiments\n{deep.experiments_summary}\n\n"
            f"## Ablation\n{deep.ablation_summary}\n\n"
            f"## Reviewer Risks\n{risks}"
        )
        report.key_insights = {
            **(report.key_insights or {}),
            "reviewer_risks": deep.reviewer_risks,
        }

    def _get_or_create(self, paper_id: UUID) -> AnalysisReport:
        pid = str(paper_id)
        q = select(AnalysisReport).where(AnalysisReport.paper_id == pid)
        found = self.session.execute(q).scalar_one_or_none()
        if found:
            return found
        report = AnalysisReport(paper_id=pid, key_insights={})
        self.session.add(report)
        try:
            self.session.flush()
        except IntegrityError:
            # 并发 skim 同一论文时，另一事务已插入行（paper_id 现为 unique）。
            # 回滚本事务未提交改动并取已存在的行，避免重复插入并防止抛 IntegrityError
            # 中断 skim 流程。此前无 unique 约束 → 重复 skim 产生重复行。
            self.session.rollback()
            return self.session.execute(q).scalar_one()
        return report

    def summaries_for_papers(self, paper_ids: list[str]) -> dict[str, str]:
        if not paper_ids:
            return {}
        q = select(AnalysisReport).where(AnalysisReport.paper_id.in_(paper_ids))
        reports = list(self.session.execute(q).scalars())
        return {x.paper_id: x.summary_md or "" for x in reports}

    def contexts_for_papers(self, paper_ids: list[str]) -> dict[str, str]:
        if not paper_ids:
            return {}
        q = select(AnalysisReport).where(AnalysisReport.paper_id.in_(paper_ids))
        reports = list(self.session.execute(q).scalars())
        out: dict[str, str] = {}
        for x in reports:
            combined = []
            if x.summary_md:
                combined.append(x.summary_md)
            if x.deep_dive_md:
                combined.append(x.deep_dive_md[:2000])
            out[x.paper_id] = "\n\n".join(combined)
        return out
