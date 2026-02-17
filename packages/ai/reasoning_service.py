"""
推理链深度分析服务
引导 LLM 进行分步推理，提供方法论推导链、实验验证链、创新性评估
@author Bamzc
"""
from __future__ import annotations

import logging
from uuid import UUID

from packages.ai.pdf_parser import PdfTextExtractor
from packages.ai.prompts import build_reasoning_prompt
from packages.config import get_settings
from packages.integrations.llm_client import LLMClient
from packages.storage.db import session_scope
from packages.storage.models import AnalysisReport
from packages.storage.repositories import (
    PaperRepository,
    PromptTraceRepository,
)

logger = logging.getLogger(__name__)


class ReasoningService:
    """推理链深度分析"""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.llm = LLMClient()
        self.pdf_extractor = PdfTextExtractor()

    def analyze(self, paper_id: UUID) -> dict:
        """对论文进行推理链深度分析"""
        # 1) 在 session 内取出所有需要的数据
        with session_scope() as session:
            from sqlalchemy import select

            paper = PaperRepository(session).get_by_id(paper_id)
            paper_title = paper.title
            paper_abstract = paper.abstract
            pdf_path = paper.pdf_path

            existing = session.execute(
                select(AnalysisReport).where(AnalysisReport.paper_id == str(paper_id))
            ).scalar_one_or_none()
            analysis_context = ""
            if existing:
                if existing.summary_md:
                    analysis_context += f"粗读报告:\n{existing.summary_md[:1500]}\n\n"
                if existing.deep_dive_md:
                    analysis_context += f"精读报告:\n{existing.deep_dive_md[:2000]}\n\n"

        # 2) 提取 PDF 文本（session 外）
        extracted_text = ""
        if pdf_path:
            extracted_text = self.pdf_extractor.extract_text(pdf_path, max_pages=12)

        # 3) LLM 调用
        prompt = build_reasoning_prompt(
            title=paper_title,
            abstract=paper_abstract,
            extracted_text=extracted_text,
            analysis_context=analysis_context,
        )

        result = self.llm.complete_json(
            prompt,
            stage="deep",
            model_override=self.settings.llm_model_deep,
            max_tokens=8192,
        )

        parsed = result.parsed_json or self._fallback(paper_title)

        # 4) 保存 token 追踪 + 结果持久化
        with session_scope() as session:
            PromptTraceRepository(session).create(
                stage="reasoning_chain",
                provider=self.llm.provider,
                model=self.settings.llm_model_deep,
                prompt_digest=prompt[:500],
                paper_id=paper_id,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                input_cost_usd=result.input_cost_usd,
                output_cost_usd=result.output_cost_usd,
                total_cost_usd=result.total_cost_usd,
            )

            paper2 = PaperRepository(session).get_by_id(paper_id)
            meta = dict(paper2.metadata_json or {})
            meta["reasoning_chain"] = parsed
            paper2.metadata_json = meta

        return {
            "paper_id": str(paper_id),
            "title": paper_title,
            "reasoning": parsed,
        }

    @staticmethod
    def _fallback(title: str) -> dict:
        return {
            "reasoning_steps": [
                {
                    "step": "分析未完成",
                    "thinking": f"论文「{title}」的推理链分析需要更多信息。",
                    "conclusion": "建议先进行粗读和精读。",
                }
            ],
            "method_chain": {
                "problem_definition": "",
                "core_hypothesis": "",
                "method_derivation": "",
                "theoretical_basis": "",
                "innovation_analysis": "",
            },
            "experiment_chain": {
                "experimental_design": "",
                "baseline_fairness": "",
                "result_validation": "",
                "ablation_insights": "",
            },
            "impact_assessment": {
                "novelty_score": 0,
                "rigor_score": 0,
                "impact_score": 0,
                "overall_assessment": "",
                "strengths": [],
                "weaknesses": [],
                "future_suggestions": [],
            },
        }
