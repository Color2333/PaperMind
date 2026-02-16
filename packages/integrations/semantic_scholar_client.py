"""
Semantic Scholar API 客户端
@author Bamzc
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass
class CitationEdge:
    source_title: str
    target_title: str
    context: str | None = None


class SemanticScholarClient:
    base_url = "https://api.semanticscholar.org/graph/v1"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key

    def fetch_edges_by_title(
        self, title: str, limit: int = 8
    ) -> list[CitationEdge]:
        paper_id = self._search_paper_id(title)
        if not paper_id:
            return []
        return self._fetch_edges(
            paper_id=paper_id,
            source_title=title,
            limit=limit,
        )

    def _search_paper_id(self, title: str) -> str | None:
        headers = {}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        params = {"query": title, "limit": 1, "fields": "title"}
        try:
            with httpx.Client(timeout=20) as client:
                resp = client.get(
                    f"{self.base_url}/paper/search",
                    params=params,
                    headers=headers,
                )
                resp.raise_for_status()
            data = resp.json().get("data", [])
            if not data:
                return None
            return data[0].get("paperId")
        except Exception:
            return None

    def _fetch_edges(
        self,
        paper_id: str,
        source_title: str,
        limit: int = 8,
    ) -> list[CitationEdge]:
        headers = {}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        fields = "references.title,citations.title"
        try:
            with httpx.Client(timeout=25) as client:
                resp = client.get(
                    f"{self.base_url}/paper/{paper_id}",
                    params={"fields": fields},
                    headers=headers,
                )
                resp.raise_for_status()
            payload = resp.json()
            edges: list[CitationEdge] = []
            for ref in payload.get("references", [])[:limit]:
                t = (ref.get("title") or "").strip()
                if t:
                    edges.append(
                        CitationEdge(
                            source_title=source_title,
                            target_title=t,
                            context="reference",
                        )
                    )
            for cit in payload.get("citations", [])[:limit]:
                t = (cit.get("title") or "").strip()
                if t:
                    edges.append(
                        CitationEdge(
                            source_title=t,
                            target_title=source_title,
                            context="citation",
                        )
                    )
            return edges
        except Exception:
            return []
