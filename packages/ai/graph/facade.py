"""GraphService — 图谱分析门面，委托 6 个子服务，对外保持原有 20 个公开方法。

@author Color2333
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from packages.ai.graph.citation import CitationService
from packages.ai.graph.overview import OverviewService
from packages.ai.graph.similarity import SimilarityService
from packages.ai.graph.survey import SurveyService
from packages.ai.graph.timeline import TimelineService
from packages.ai.graph.wiki import WikiService
from packages.ai.wiki_context import WikiContextGatherer
from packages.config import get_settings
from packages.integrations.citation_provider import CitationProvider
from packages.integrations.llm_client import LLMClient

if TYPE_CHECKING:
    from collections.abc import Callable


class GraphService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.citations = CitationProvider(
            openalex_email=self.settings.openalex_email,
            scholar_api_key=self.settings.semantic_scholar_api_key,
        )
        # 保留 self.scholar 兼容别名
        self.scholar = self.citations
        self.llm = LLMClient()
        self.context_gatherer = WikiContextGatherer()

        # 实例化子服务，注入各自所需的共享客户端
        self._citation = CitationService(self.settings, self.citations, self.scholar)
        self._overview = OverviewService()
        self._timeline = TimelineService()
        self._survey = SurveyService(self._timeline, self.llm, self.settings)
        self._wiki = WikiService(
            self._citation,
            self._timeline,
            self._survey,
            self.llm,
            self.context_gatherer,
            self.scholar,
            self.settings,
        )
        self._similarity = SimilarityService()

    # ---------- CitationService (8) ----------
    def sync_citations_for_paper(self, paper_id: str, limit: int = 8) -> dict:
        return self._citation.sync_citations_for_paper(paper_id, limit=limit)

    def sync_citations_for_topic(
        self,
        topic_id: str,
        paper_limit: int = 30,
        edge_limit_per_paper: int = 6,
    ) -> dict:
        return self._citation.sync_citations_for_topic(
            topic_id,
            paper_limit=paper_limit,
            edge_limit_per_paper=edge_limit_per_paper,
        )

    def auto_link_citations(self, paper_ids: list[str]) -> dict:
        return self._citation.auto_link_citations(paper_ids)

    def sync_incremental(
        self,
        paper_limit: int = 40,
        edge_limit_per_paper: int = 6,
    ) -> dict:
        return self._citation.sync_incremental(
            paper_limit=paper_limit,
            edge_limit_per_paper=edge_limit_per_paper,
        )

    def citation_tree(self, root_paper_id: str, depth: int = 2) -> dict:
        return self._citation.citation_tree(root_paper_id, depth=depth)

    def citation_detail(self, paper_id: str) -> dict:
        return self._citation.citation_detail(paper_id)

    def topic_citation_network(self, topic_id: str) -> dict:
        return self._citation.topic_citation_network(topic_id)

    def topic_deep_trace(self, topic_id: str, max_concurrency: int = 3) -> dict:
        return self._citation.topic_deep_trace(topic_id, max_concurrency=max_concurrency)

    # ---------- OverviewService (4) ----------
    def library_overview(self) -> dict:
        return self._overview.library_overview()

    def cross_topic_bridges(self) -> dict:
        return self._overview.cross_topic_bridges()

    def research_frontier(self, days: int = 90) -> dict:
        return self._overview.research_frontier(days=days)

    def cocitation_clusters(self, min_cocite: int = 2) -> dict:
        return self._overview.cocitation_clusters(min_cocite=min_cocite)

    # ---------- TimelineService (2) ----------
    def timeline(self, keyword: str, limit: int = 100) -> dict:
        return self._timeline.timeline(keyword, limit=limit)

    def quality_metrics(self, keyword: str, limit: int = 120) -> dict:
        return self._timeline.quality_metrics(keyword, limit=limit)

    # ---------- SurveyService (3) ----------
    def weekly_evolution(self, keyword: str, limit: int = 160) -> dict:
        return self._survey.weekly_evolution(keyword, limit=limit)

    def survey(self, keyword: str, limit: int = 120) -> dict:
        return self._survey.survey(keyword, limit=limit)

    def detect_research_gaps(
        self,
        keyword: str,
        limit: int = 120,
    ) -> dict:
        return self._survey.detect_research_gaps(keyword, limit=limit)

    # ---------- WikiService (2 public) ----------
    def paper_wiki(self, paper_id: str) -> dict:
        return self._wiki.paper_wiki(paper_id)

    def topic_wiki(
        self,
        keyword: str,
        limit: int = 120,
        progress_callback: Callable[[str, int, int], None] | None = None,
    ) -> dict:
        return self._wiki.topic_wiki(keyword, limit=limit, progress_callback=progress_callback)

    # ---------- SimilarityService (1) ----------
    def similarity_map(
        self,
        topic_id: str | None = None,
        limit: int = 200,
    ) -> dict:
        return self._similarity.similarity_map(topic_id=topic_id, limit=limit)
