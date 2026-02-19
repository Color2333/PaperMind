"""
RAG 检索增强生成服务
@author Bamzc
"""
from __future__ import annotations

import json
import logging
from uuid import UUID

from packages.ai.cost_guard import CostGuardService
from packages.ai.prompts import build_rag_prompt
from packages.domain.schemas import AskResponse
from packages.integrations.llm_client import LLMClient
from packages.storage.db import session_scope
from packages.storage.repositories import (
    AnalysisRepository,
    PaperRepository,
    PromptTraceRepository,
)

logger = logging.getLogger(__name__)


class RAGService:
    def __init__(self) -> None:
        self.llm = LLMClient()

    def ask(
        self, question: str, top_k: int = 5
    ) -> AskResponse:
        with session_scope() as session:
            repo = PaperRepository(session)
            lexical = repo.full_text_candidates(
                query=question, limit=max(top_k, 8)
            )
            qvec = self.llm.embed_text(question)
            semantic = repo.semantic_candidates(
                query_vector=qvec, limit=max(top_k, 8)
            )
            candidates = []
            seen: set[str] = set()
            for p in lexical + semantic:
                if p.id in seen:
                    continue
                seen.add(p.id)
                candidates.append(p)
            candidates = candidates[: max(top_k, 8)]
            if not candidates:
                return AskResponse(
                    answer="当前知识库没有足够上下文。",
                    cited_paper_ids=[],
                )
            paper_ids = [p.id for p in candidates[:top_k]]
            report_ctx = AnalysisRepository(
                session
            ).contexts_for_papers(paper_ids)
            contexts = []
            evidence = []
            for p in candidates[:top_k]:
                rpt = report_ctx.get(p.id, "") or ""
                snippet = (
                    f"{p.abstract[:260]}\n{rpt[:320]}"
                )
                contexts.append(
                    f"{p.title}\n"
                    f"{p.abstract[:500]}\n"
                    f"{rpt[:1200]}"
                )
                evidence.append(
                    {
                        "paper_id": p.id,
                        "title": p.title,
                        "snippet": snippet.strip(),
                        "source": "abstract+analysis",
                    }
                )
            prompt = build_rag_prompt(question, contexts)
            decision = CostGuardService(
                session, self.llm
            ).choose_model(
                stage="rag",
                prompt=prompt,
                default_model=self.llm.settings.llm_model_skim,
            )
            result = self.llm.complete_json(
                prompt,
                stage="rag",
                model_override=decision.chosen_model,
            )
            answer = result.content
            if result.parsed_json:
                answer = str(
                    result.parsed_json.get("answer", answer)
                )
            PromptTraceRepository(session).create(
                stage="rag",
                provider=self.llm.provider,
                model=decision.chosen_model,
                prompt_digest=prompt[:500],
                paper_id=None,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                input_cost_usd=result.input_cost_usd,
                output_cost_usd=result.output_cost_usd,
                total_cost_usd=result.total_cost_usd,
            )
            return AskResponse(
                answer=answer,
                cited_paper_ids=paper_ids,
                evidence=evidence,
            )

    def ask_iterative(
        self,
        question: str,
        max_rounds: int = 3,
        initial_top_k: int = 5,
        on_progress: callable | None = None,
    ) -> AskResponse:
        """多轮迭代 RAG：自动评估答案质量，不满意则补充检索"""
        top_k = initial_top_k
        all_cited: list[str] = []
        all_evidence: list[dict] = []
        current_answer = ""
        rounds_done = 0
        query = question

        for rnd in range(max_rounds):
            rounds_done = rnd + 1
            if on_progress:
                on_progress(f"第 {rounds_done} 轮检索（top_k={top_k}）...")

            resp = self.ask(query, top_k=top_k)
            current_answer = resp.answer

            # 合并引用（去重）
            for pid in resp.cited_paper_ids:
                if pid not in all_cited:
                    all_cited.append(pid)
            seen_ids = {e.get("paper_id") for e in all_evidence}
            for e in (resp.evidence or []):
                if e.get("paper_id") not in seen_ids:
                    all_evidence.append(e)
                    seen_ids.add(e.get("paper_id"))

            if rnd >= max_rounds - 1:
                break

            # LLM 评估答案质量
            if on_progress:
                on_progress("评估答案完整性...")

            eval_result = self._evaluate_answer(question, current_answer)
            if eval_result.get("sufficient", True):
                if on_progress:
                    on_progress("答案充分，无需继续检索")
                break

            # 不满意 → 补充检索
            missing = eval_result.get("missing_aspects", [])
            new_queries = eval_result.get("suggested_queries", [])
            if on_progress:
                on_progress(f"答案不够完整（缺失：{', '.join(missing[:2])}），补充检索...")

            # 用补充关键词扩展检索
            if new_queries:
                query = f"{question} {' '.join(new_queries[:2])}"
            top_k = min(top_k + 5, 20)

        return AskResponse(
            answer=current_answer,
            cited_paper_ids=all_cited,
            evidence=all_evidence,
            rounds=rounds_done,
        )

    def _evaluate_answer(self, question: str, answer: str) -> dict:
        """用 LLM 评估 RAG 答案是否充分"""
        eval_prompt = (
            "你是答案质量评估专家。请评估以下问答的答案质量，输出严格 JSON。\n"
            "评估维度：答案是否完整回答了问题、是否有足够的证据支持、是否还有重要方面未覆盖。\n\n"
            f"问题：{question}\n\n"
            f"答案：{answer[:2000]}\n\n"
            '输出格式：{{"sufficient": true/false, "missing_aspects": ["缺失方面1"], "suggested_queries": ["补充搜索词1"]}}'
        )
        try:
            result = self.llm.complete_json(eval_prompt, stage="rag_eval", max_tokens=300)
            if result.parsed_json:
                return result.parsed_json
        except Exception as exc:
            logger.warning("RAG eval failed: %s", exc)
        return {"sufficient": True}

    def similar_papers(
        self, paper_id: UUID, top_k: int = 5
    ) -> list[UUID]:
        with session_scope() as session:
            repo = PaperRepository(session)
            paper = repo.get_by_id(paper_id)
            if not paper.embedding:
                return []
            peers = repo.similar_by_embedding(
                paper.embedding, exclude=paper_id, limit=top_k
            )
            return [p.id for p in peers]
