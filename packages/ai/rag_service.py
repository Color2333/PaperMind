"""
RAG 检索增强生成服务
@author Bamzc
"""
from __future__ import annotations

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
