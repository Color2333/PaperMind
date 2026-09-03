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
