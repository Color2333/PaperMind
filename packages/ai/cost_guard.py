"""
LLM 成本守卫 - 自动降级模型选择
@author Bamzc
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from packages.config import get_settings
from packages.integrations.llm_client import LLMClient
from packages.storage.repositories import PromptTraceRepository


@dataclass
class GuardDecision:
    chosen_model: str
    note: str


class CostGuardService:
    def __init__(self, session: Session, llm: LLMClient) -> None:
        self.session = session
        self.llm = llm
        self.settings = get_settings()
        self.trace_repo = PromptTraceRepository(session)

    def choose_model(
        self,
        *,
        stage: str,
        prompt: str,
        default_model: str,
    ) -> GuardDecision:
        if not self.settings.cost_guard_enabled:
            return GuardDecision(
                chosen_model=default_model,
                note="cost_guard_disabled",
            )

        expected_out = self._expected_output_tokens(stage)
        in_tokens = len(prompt) // 4
        _, _, predicted_cost = self.llm.estimate_cost(
            model=default_model,
            input_tokens=in_tokens,
            output_tokens=expected_out,
        )

        day_cost = float(
            self.trace_repo.summarize_costs(days=1)["total_cost_usd"]
        )
        fallback = self.settings.llm_model_fallback
        budget_per_call = self.settings.per_call_budget_usd
        budget_daily = self.settings.daily_budget_usd

        if budget_per_call > 0 and predicted_cost > budget_per_call:
            _, _, fb_cost = self.llm.estimate_cost(
                model=fallback,
                input_tokens=in_tokens,
                output_tokens=expected_out,
            )
            note = (
                f"degraded_by_per_call_budget "
                f"default={default_model} fallback={fallback} "
                f"pred={predicted_cost:.6f} "
                f"fb_pred={fb_cost:.6f} "
                f"budget={budget_per_call:.6f}"
            )
            return GuardDecision(chosen_model=fallback, note=note)

        if budget_daily > 0 and (day_cost + predicted_cost) > budget_daily:
            _, _, fb_cost = self.llm.estimate_cost(
                model=fallback,
                input_tokens=in_tokens,
                output_tokens=expected_out,
            )
            note = (
                f"degraded_by_daily_budget "
                f"default={default_model} fallback={fallback} "
                f"day={day_cost:.6f} pred={predicted_cost:.6f} "
                f"fb_pred={fb_cost:.6f} "
                f"budget={budget_daily:.6f}"
            )
            return GuardDecision(chosen_model=fallback, note=note)

        return GuardDecision(
            chosen_model=default_model,
            note=(
                f"default_model_kept model={default_model} "
                f"pred={predicted_cost:.6f} "
                f"day_spent={day_cost:.6f}"
            ),
        )

    @staticmethod
    def _expected_output_tokens(stage: str) -> int:
        if stage == "deep":
            return 1200
        if stage == "rag":
            return 700
        return 500
