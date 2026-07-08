"""时间线与质量评估服务。"""

from __future__ import annotations

import logging
from datetime import date

from packages.ai.graph._common import _milestones_by_year, _pagerank
from packages.storage.db import session_scope
from packages.storage.repositories import (
    CitationRepository,
    PaperRepository,
)

logger = logging.getLogger(__name__)


class TimelineService:
    def __init__(self) -> None:
        pass

    def timeline(self, keyword: str, limit: int = 100) -> dict:
        with session_scope() as session:
            papers = PaperRepository(session).full_text_candidates(keyword, limit=limit)
            edges = CitationRepository(session).list_all()
            nodes = {p.id: p for p in papers}
            indegree: dict[str, int] = {p.id: 0 for p in papers}
            outdegree: dict[str, int] = {p.id: 0 for p in papers}
            for e in edges:
                if e.target_paper_id in nodes and e.source_paper_id in nodes:
                    indegree[e.target_paper_id] += 1
                    outdegree[e.source_paper_id] += 1
            pagerank = _pagerank(nodes=list(nodes.keys()), edges=edges)
            items = []
            for p in papers:
                year = p.publication_date.year if isinstance(p.publication_date, date) else 1900
                pr = pagerank.get(p.id, 0.0)
                ind = indegree.get(p.id, 0)
                score = 0.65 * ind + 0.35 * pr * 100.0
                items.append(
                    {
                        "paper_id": p.id,
                        "title": p.title,
                        "year": year,
                        "indegree": ind,
                        "outdegree": outdegree.get(p.id, 0),
                        "pagerank": pr,
                        "seminal_score": score,
                        "why_seminal": (f"indegree={ind}, pagerank={pr:.4f}, score={score:.3f}"),
                    }
                )
        items.sort(
            key=lambda x: (
                x["year"],
                -x["indegree"],
                x["title"],
            )
        )
        seminal = sorted(
            items,
            key=lambda x: (-x["seminal_score"], x["year"]),
        )[:10]
        milestones = _milestones_by_year(items)
        return {
            "keyword": keyword,
            "timeline": items,
            "seminal": seminal,
            "milestones": milestones,
        }

    def quality_metrics(self, keyword: str, limit: int = 120) -> dict:
        with session_scope() as session:
            papers = PaperRepository(session).full_text_candidates(keyword, limit=limit)
            paper_ids = [p.id for p in papers]
            edges = CitationRepository(session).list_for_paper_ids(paper_ids)
            node_set = set(paper_ids)
            internal_edges = [
                e for e in edges if e.source_paper_id in node_set and e.target_paper_id in node_set
            ]
            connected_nodes: set[str] = set()
            for e in internal_edges:
                connected_nodes.add(e.source_paper_id)
                connected_nodes.add(e.target_paper_id)
            with_pub = sum(1 for p in papers if p.publication_date is not None)
        n = max(len(paper_ids), 1)
        ie = len(internal_edges)
        return {
            "keyword": keyword,
            "node_count": len(paper_ids),
            "edge_count": ie,
            "density": ie / max(n * max(n - 1, 1), 1),
            "connected_node_ratio": (len(connected_nodes) / n),
            "publication_date_coverage": with_pub / n,
        }
