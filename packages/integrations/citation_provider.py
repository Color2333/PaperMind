"""
双源引用数据提供者
OpenAlex（10 req/s）为主力，Semantic Scholar 为兜底
@author Bamzc
"""
from __future__ import annotations

import logging

from packages.integrations.openalex_client import OpenAlexClient
from packages.integrations.semantic_scholar_client import (
    CitationEdge,
    RichCitationInfo,
    SemanticScholarClient,
)

logger = logging.getLogger(__name__)


class CitationProvider:
    """统一的引用数据入口，自动 fallback"""

    def __init__(
        self,
        openalex_email: str | None = None,
        scholar_api_key: str | None = None,
    ) -> None:
        self.openalex = OpenAlexClient(email=openalex_email)
        self.scholar = SemanticScholarClient(api_key=scholar_api_key)

    def fetch_edges_by_title(
        self, title: str, limit: int = 8, *, arxiv_id: str | None = None,
    ) -> list[CitationEdge]:
        try:
            edges = self.openalex.fetch_edges_by_title(title, limit=limit, arxiv_id=arxiv_id)
            if edges:
                logger.debug("OpenAlex returned %d edges for '%s'", len(edges), title[:50])
                return edges
        except Exception as exc:
            logger.warning("OpenAlex failed for '%s': %s, falling back to Scholar", title[:50], exc)

        try:
            edges = self.scholar.fetch_edges_by_title(title, limit=limit, arxiv_id=arxiv_id)
            if edges:
                logger.debug("Scholar returned %d edges for '%s'", len(edges), title[:50])
            return edges
        except Exception as exc:
            logger.warning("Scholar also failed for '%s': %s", title[:50], exc)
            return []

    def fetch_rich_citations(
        self,
        title: str,
        ref_limit: int = 30,
        cite_limit: int = 30,
        *,
        arxiv_id: str | None = None,
    ) -> list[RichCitationInfo]:
        try:
            results = self.openalex.fetch_rich_citations(
                title, ref_limit=ref_limit, cite_limit=cite_limit, arxiv_id=arxiv_id,
            )
            if results:
                logger.debug("OpenAlex rich citations: %d for '%s'", len(results), title[:50])
                return results
        except Exception as exc:
            logger.warning("OpenAlex rich failed for '%s': %s, falling back", title[:50], exc)

        try:
            return self.scholar.fetch_rich_citations(
                title, ref_limit=ref_limit, cite_limit=cite_limit, arxiv_id=arxiv_id,
            )
        except Exception as exc:
            logger.warning("Scholar rich also failed for '%s': %s", title[:50], exc)
            return []

    def fetch_batch_metadata(self, titles: list[str], max_papers: int = 10) -> list[dict]:
        try:
            results = self.openalex.fetch_batch_metadata(titles, max_papers=max_papers)
            if results:
                return results
        except Exception as exc:
            logger.warning("OpenAlex batch metadata failed: %s, falling back", exc)

        try:
            return self.scholar.fetch_batch_metadata(titles, max_papers=max_papers)
        except Exception as exc:
            logger.warning("Scholar batch metadata also failed: %s", exc)
            return []

    def fetch_paper_metadata(self, title: str, *, arxiv_id: str | None = None) -> dict | None:
        """单篇元数据，OpenAlex 不直接有此接口，先查 batch 再 fallback"""
        try:
            results = self.openalex.fetch_batch_metadata([title], max_papers=1)
            if results:
                return results[0]
        except Exception:
            pass
        return self.scholar.fetch_paper_metadata(title, arxiv_id=arxiv_id)

    def close(self) -> None:
        self.openalex.close()
        self.scholar.close()
