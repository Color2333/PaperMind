"""
Prompt 调用追踪数据仓储
@author Color2333
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import func, select

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.orm import Session

from packages.storage.models import PromptTrace


class PromptTraceRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        *,
        stage: str,
        provider: str,
        model: str,
        prompt_digest: str,
        paper_id: UUID | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        input_cost_usd: float | None = None,
        output_cost_usd: float | None = None,
        total_cost_usd: float | None = None,
    ) -> None:
        self.session.add(
            PromptTrace(
                stage=stage,
                provider=provider,
                model=model,
                prompt_digest=prompt_digest,
                paper_id=str(paper_id) if paper_id else None,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                input_cost_usd=input_cost_usd,
                output_cost_usd=output_cost_usd,
                total_cost_usd=total_cost_usd,
            )
        )

    def summarize_costs(self, days: int = 7) -> dict:
        since = None if days <= 0 else datetime.now(UTC) - timedelta(days=days)
        base_filter = [] if since is None else [PromptTrace.created_at >= since]

        total_q = select(
            func.count(PromptTrace.id),
            func.coalesce(func.sum(PromptTrace.input_tokens), 0),
            func.coalesce(func.sum(PromptTrace.output_tokens), 0),
            func.coalesce(func.sum(PromptTrace.total_cost_usd), 0.0),
        )
        if since:
            total_q = total_q.where(*base_filter)
        count, in_tokens, out_tokens, total_cost = self.session.execute(total_q).one()

        by_stage_q = select(
            PromptTrace.stage,
            func.count(PromptTrace.id),
            func.coalesce(func.sum(PromptTrace.total_cost_usd), 0.0),
            func.coalesce(func.sum(PromptTrace.input_tokens), 0),
            func.coalesce(func.sum(PromptTrace.output_tokens), 0),
        )
        if since:
            by_stage_q = by_stage_q.where(*base_filter)
        by_stage_q = by_stage_q.group_by(PromptTrace.stage)

        by_model_q = select(
            PromptTrace.provider,
            PromptTrace.model,
            func.count(PromptTrace.id),
            func.coalesce(func.sum(PromptTrace.total_cost_usd), 0.0),
            func.coalesce(func.sum(PromptTrace.input_tokens), 0),
            func.coalesce(func.sum(PromptTrace.output_tokens), 0),
        )
        if since:
            by_model_q = by_model_q.where(*base_filter)
        by_model_q = by_model_q.group_by(PromptTrace.provider, PromptTrace.model)

        by_stage = [
            {
                "stage": stage,
                "calls": calls,
                "total_cost_usd": float(cost),
                "input_tokens": int(in_t or 0),
                "output_tokens": int(out_t or 0),
            }
            for stage, calls, cost, in_t, out_t in self.session.execute(by_stage_q).all()
        ]
        by_model = [
            {
                "provider": prov,
                "model": mdl,
                "calls": calls,
                "total_cost_usd": float(cost),
                "input_tokens": int(in_t or 0),
                "output_tokens": int(out_t or 0),
            }
            for prov, mdl, calls, cost, in_t, out_t in self.session.execute(by_model_q).all()
        ]

        return {
            "window_days": days,
            "calls": int(count),
            "input_tokens": int(in_tokens or 0),
            "output_tokens": int(out_tokens or 0),
            "total_cost_usd": float(total_cost or 0.0),
            "by_stage": by_stage,
            "by_model": by_model,
        }
