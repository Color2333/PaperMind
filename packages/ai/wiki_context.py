"""
Wiki 生成上下文收集模块
从多源聚合富化上下文供 Wiki 生成使用
@author Bamzc
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from uuid import UUID

from packages.ai.pdf_parser import PdfTextExtractor
from packages.integrations.llm_client import LLMClient
from packages.storage.db import session_scope
from packages.storage.repositories import (
    AnalysisRepository,
    CitationRepository,
    PaperRepository,
)

logger = logging.getLogger(__name__)


def _extract_year(pub_date: date | None) -> int | None:
    if pub_date is None:
        return None
    if isinstance(pub_date, date):
        return pub_date.year
    return None


class WikiContextGatherer:
    """Gathers enriched context from multiple sources for wiki generation"""

    def __init__(self) -> None:
        self.llm = LLMClient()
        self.pdf_extractor = PdfTextExtractor()

    def gather_topic_context(
        self, keyword: str, limit: int = 120
    ) -> dict:
        """
        Returns {
            "paper_contexts": list[dict],   # title, year, abstract, analysis, has_embedding
            "citation_contexts": list[str],  # citation edge context strings
            "pdf_excerpts": list[dict],      # title, excerpt
        }
        """
        result: dict = {
            "paper_contexts": [],
            "citation_contexts": [],
            "pdf_excerpts": [],
        }
        try:
            with session_scope() as session:
                paper_repo = PaperRepository(session)
                analysis_repo = AnalysisRepository(session)
                citation_repo = CitationRepository(session)

                half = max(limit // 2, 1)
                full_text_papers = paper_repo.full_text_candidates(
                    keyword, limit=half
                )
                query_vector = self.llm.embed_text(keyword)
                semantic_papers = paper_repo.semantic_candidates(
                    query_vector, limit=half
                )

                seen: set[str] = set()
                merged: list = []
                for p in full_text_papers + semantic_papers:
                    if p.id in seen:
                        continue
                    seen.add(p.id)
                    merged.append(p)
                merged = merged[:limit]

                paper_ids = [p.id for p in merged]
                analysis_map = analysis_repo.contexts_for_papers(paper_ids)
                citations = citation_repo.list_for_paper_ids(paper_ids)

                citation_contexts: list[str] = []
                for c in citations:
                    if c.context and c.context.strip():
                        citation_contexts.append(c.context.strip())
                result["citation_contexts"] = citation_contexts

                for p in merged:
                    ctx = {
                        "title": p.title or "",
                        "year": _extract_year(p.publication_date),
                        "abstract": p.abstract or "",
                        "analysis": analysis_map.get(p.id, ""),
                        "has_embedding": p.embedding is not None,
                    }
                    result["paper_contexts"].append(ctx)

                pdf_count = 0
                for p in merged:
                    if pdf_count >= 5:
                        break
                    if not p.pdf_path:
                        continue
                    path = Path(p.pdf_path)
                    if not path.exists():
                        continue
                    try:
                        excerpt = self.pdf_extractor.extract_text(
                            p.pdf_path, max_pages=12
                        )
                        if excerpt:
                            result["pdf_excerpts"].append(
                                {"title": p.title or "", "excerpt": excerpt}
                            )
                            pdf_count += 1
                    except Exception as exc:
                        logger.warning(
                            "PDF extract failed for %s: %s",
                            p.pdf_path,
                            exc,
                        )

        except Exception as exc:
            logger.exception("gather_topic_context failed: %s", exc)

        return result

    def gather_paper_context(self, paper_id: str) -> dict:
        """
        Returns {
            "paper": dict,          # title, abstract, arxiv_id, analysis
            "related_papers": list[dict],  # title, year, abstract
            "citation_contexts": list[str],
            "pdf_excerpt": str,     # PDF text extract for this paper
            "ancestor_titles": list[str],
            "descendant_titles": list[str],
        }
        """
        result: dict = {
            "paper": {},
            "related_papers": [],
            "citation_contexts": [],
            "pdf_excerpt": "",
            "ancestor_titles": [],
            "descendant_titles": [],
        }
        try:
            with session_scope() as session:
                paper_repo = PaperRepository(session)
                analysis_repo = AnalysisRepository(session)
                citation_repo = CitationRepository(session)

                paper = paper_repo.get_by_id(UUID(paper_id))
                analysis_map = analysis_repo.contexts_for_papers([paper_id])
                result["paper"] = {
                    "title": paper.title or "",
                    "abstract": paper.abstract or "",
                    "arxiv_id": paper.arxiv_id or "",
                    "analysis": analysis_map.get(paper_id, ""),
                }

                vector = paper.embedding
                if not vector and (paper.title or paper.abstract):
                    text = f"{paper.title or ''}\n{paper.abstract or ''}".strip()
                    vector = self.llm.embed_text(text)
                if vector:
                    related = paper_repo.similar_by_embedding(
                        vector, UUID(paper_id), limit=5
                    )
                    for r in related:
                        result["related_papers"].append({
                            "title": r.title or "",
                            "year": _extract_year(r.publication_date),
                            "abstract": r.abstract or "",
                        })

                citations = citation_repo.list_for_paper_ids([paper_id])
                citation_contexts: list[str] = []
                ancestor_ids: set[str] = set()
                descendant_ids: set[str] = set()
                for c in citations:
                    if c.context and c.context.strip():
                        citation_contexts.append(c.context.strip())
                    if c.target_paper_id == paper_id:
                        ancestor_ids.add(c.source_paper_id)
                    if c.source_paper_id == paper_id:
                        descendant_ids.add(c.target_paper_id)
                result["citation_contexts"] = citation_contexts

                all_related_ids = list(ancestor_ids | descendant_ids)
                if all_related_ids:
                    papers_by_id = {
                        p.id: p
                        for p in paper_repo.list_by_ids(all_related_ids)
                    }
                    for aid in ancestor_ids:
                        p = papers_by_id.get(aid)
                        if p and p.title:
                            result["ancestor_titles"].append(p.title)
                    for did in descendant_ids:
                        p = papers_by_id.get(did)
                        if p and p.title:
                            result["descendant_titles"].append(p.title)

                if paper.pdf_path:
                    path = Path(paper.pdf_path)
                    if path.exists():
                        try:
                            result["pdf_excerpt"] = (
                                self.pdf_extractor.extract_text(
                                    paper.pdf_path, max_pages=12
                                )
                                or ""
                            )
                        except Exception as exc:
                            logger.warning(
                                "PDF extract failed for %s: %s",
                                paper.pdf_path,
                                exc,
                            )

        except ValueError as exc:
            logger.warning("gather_paper_context paper not found: %s", exc)
        except Exception as exc:
            logger.exception("gather_paper_context failed: %s", exc)

        return result
