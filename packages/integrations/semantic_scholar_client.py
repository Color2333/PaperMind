"""
Semantic Scholar API 客户端
连接复用 + 429 重试 + 日志
@author Bamzc
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

_RETRY_CODES = {429, 500, 502, 503}
_MAX_RETRIES = 8
_BASE_DELAY = 3.0
_MAX_DELAY = 30.0


@dataclass
class CitationEdge:
    source_title: str
    target_title: str
    context: str | None = None


@dataclass
class RichCitationInfo:
    """丰富的引用/参考文献信息"""

    scholar_id: str | None
    title: str
    year: int | None = None
    venue: str | None = None
    citation_count: int | None = None
    arxiv_id: str | None = None
    abstract: str | None = None
    direction: str = "reference"  # "reference" or "citation"


def _extract_arxiv_id(external_ids: dict | None) -> str | None:
    """从 Semantic Scholar externalIds 提取 arxiv_id"""
    if not external_ids or not isinstance(external_ids, dict):
        return None
    return external_ids.get("ArXiv")


class SemanticScholarClient:
    base_url = "https://api.semanticscholar.org/graph/v1"

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key
        self._client: httpx.Client | None = None

    @property
    def client(self) -> httpx.Client:
        """复用 httpx.Client 连接"""
        if self._client is None or self._client.is_closed:
            headers = {}
            if self.api_key:
                headers["x-api-key"] = self.api_key
            self._client = httpx.Client(
                base_url=self.base_url,
                timeout=25,
                headers=headers,
                follow_redirects=True,
            )
        return self._client

    def _get(self, path: str, params: dict | None = None) -> dict | None:
        """带重试的 GET 请求，429 指数退避最长 15s"""
        for attempt in range(_MAX_RETRIES):
            try:
                resp = self.client.get(path, params=params)
                if resp.status_code in _RETRY_CODES:
                    delay = min(_BASE_DELAY * (2**attempt), _MAX_DELAY)
                    logger.warning(
                        "Scholar API %d for %s, retry %d/%d in %.1fs",
                        resp.status_code,
                        path,
                        attempt + 1,
                        _MAX_RETRIES,
                        delay,
                    )
                    time.sleep(delay)
                    continue
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                return resp.json()
            except httpx.TimeoutException:
                logger.warning("Scholar API timeout for %s, retry %d", path, attempt + 1)
                time.sleep(_BASE_DELAY)
            except Exception as exc:
                logger.warning("Scholar API error for %s: %s", path, exc)
                return None
        logger.error("Scholar API exhausted retries for %s", path)
        return None

    def fetch_edges_by_title(
        self,
        title: str,
        limit: int = 8,
        *,
        arxiv_id: str | None = None,
    ) -> list[CitationEdge]:
        paper_id = self.resolve_paper_id(arxiv_id=arxiv_id, title=title)
        if not paper_id:
            return []
        return self._fetch_edges(
            paper_id=paper_id,
            source_title=title,
            limit=limit,
        )

    def resolve_paper_id(
        self,
        *,
        arxiv_id: str | None = None,
        title: str | None = None,
    ) -> str | None:
        """优先用 arxiv_id 直接定位，退而求其次标题搜索"""
        if arxiv_id:
            clean = arxiv_id.split("v")[0] if "v" in arxiv_id else arxiv_id
            data = self._get(
                f"/paper/ARXIV:{clean}",
                params={"fields": "paperId"},
            )
            if data and data.get("paperId"):
                return data["paperId"]
            logger.info("ARXIV:%s not found, falling back to title search", clean)

        if title:
            return self._search_paper_id(title)
        return None

    def _search_paper_id(self, title: str) -> str | None:
        data = self._get(
            "/paper/search",
            params={"query": title, "limit": 1, "fields": "title"},
        )
        if not data:
            return None
        items = data.get("data", [])
        return items[0].get("paperId") if items else None

    def _fetch_edges(
        self,
        paper_id: str,
        source_title: str,
        limit: int = 8,
    ) -> list[CitationEdge]:
        fields = "references.title,citations.title"
        payload = self._get(
            f"/paper/{paper_id}",
            params={"fields": fields},
        )
        if not payload:
            return []
        edges: list[CitationEdge] = []
        for ref in (payload.get("references") or [])[:limit]:
            t = (ref.get("title") or "").strip()
            if t:
                edges.append(
                    CitationEdge(
                        source_title=source_title,
                        target_title=t,
                        context="reference",
                    )
                )
        for cit in (payload.get("citations") or [])[:limit]:
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

    def fetch_paper_metadata(
        self,
        title: str,
        *,
        arxiv_id: str | None = None,
    ) -> dict | None:
        paper_id = self.resolve_paper_id(arxiv_id=arxiv_id, title=title)
        if not paper_id:
            return None
        fields = "title,year,citationCount,influentialCitationCount,venue,fieldsOfStudy,tldr"
        data = self._get(
            f"/paper/{paper_id}",
            params={"fields": fields},
        )
        if not data:
            return None
        tldr_obj = data.get("tldr")
        tldr_text = tldr_obj.get("text") if isinstance(tldr_obj, dict) else None
        return {
            "title": data.get("title"),
            "year": data.get("year"),
            "citationCount": data.get("citationCount"),
            "influentialCitationCount": data.get("influentialCitationCount"),
            "venue": data.get("venue"),
            "fieldsOfStudy": data.get("fieldsOfStudy") or [],
            "tldr": tldr_text,
        }

    def fetch_batch_metadata(self, titles: list[str], max_papers: int = 10) -> list[dict]:
        results: list[dict] = []
        for title in titles[:max_papers]:
            meta = self.fetch_paper_metadata(title)
            if meta is not None:
                results.append(meta)
        return results

    def fetch_rich_citations(
        self,
        title: str,
        ref_limit: int = 30,
        cite_limit: int = 30,
        *,
        arxiv_id: str | None = None,
    ) -> list[RichCitationInfo]:
        """获取论文的丰富引用/参考文献信息，优先 arxiv_id 直查"""
        paper_id = self.resolve_paper_id(arxiv_id=arxiv_id, title=title)
        if not paper_id:
            return []

        fields = (
            "references.paperId,references.title,references.year,"
            "references.venue,references.citationCount,"
            "references.externalIds,references.abstract,"
            "citations.paperId,citations.title,citations.year,"
            "citations.venue,citations.citationCount,"
            "citations.externalIds,citations.abstract"
        )
        payload = self._get(
            f"/paper/{paper_id}",
            params={"fields": fields},
        )
        if not payload:
            return []

        results: list[RichCitationInfo] = []

        for ref in (payload.get("references") or [])[:ref_limit]:
            t = (ref.get("title") or "").strip()
            if not t:
                continue
            results.append(
                RichCitationInfo(
                    scholar_id=ref.get("paperId"),
                    title=t,
                    year=ref.get("year"),
                    venue=(ref.get("venue") or "").strip() or None,
                    citation_count=ref.get("citationCount"),
                    arxiv_id=_extract_arxiv_id(ref.get("externalIds")),
                    abstract=(ref.get("abstract") or "")[:500] or None,
                    direction="reference",
                )
            )

        for cit in (payload.get("citations") or [])[:cite_limit]:
            t = (cit.get("title") or "").strip()
            if not t:
                continue
            results.append(
                RichCitationInfo(
                    scholar_id=cit.get("paperId"),
                    title=t,
                    year=cit.get("year"),
                    venue=(cit.get("venue") or "").strip() or None,
                    citation_count=cit.get("citationCount"),
                    arxiv_id=_extract_arxiv_id(cit.get("externalIds")),
                    abstract=(cit.get("abstract") or "")[:500] or None,
                    direction="citation",
                )
            )

        return results

    def fetch_paper_by_scholar_id(self, scholar_id: str) -> dict | None:
        """按 Semantic Scholar paperId 获取论文详细信息（含作者）"""
        fields = (
            "title,year,venue,citationCount,abstract,"
            "externalIds,authors,publicationDate,fieldsOfStudy"
        )
        data = self._get(
            f"/paper/{scholar_id}",
            params={"fields": fields},
        )
        if not data:
            return None
        authors = []
        for a in data.get("authors") or []:
            name = (a.get("name") or "").strip()
            if name:
                authors.append(name)
        pub_date = data.get("publicationDate")
        return {
            "scholar_id": data.get("paperId"),
            "title": (data.get("title") or "").strip(),
            "year": data.get("year"),
            "venue": (data.get("venue") or "").strip() or None,
            "citation_count": data.get("citationCount"),
            "abstract": (data.get("abstract") or "").strip() or None,
            "arxiv_id": _extract_arxiv_id(data.get("externalIds")),
            "authors": authors,
            "publication_date": pub_date,
            "fields_of_study": data.get("fieldsOfStudy") or [],
        }

    def close(self) -> None:
        if self._client and not self._client.is_closed:
            self._client.close()

    def __del__(self) -> None:
        self.close()
