"""
Semantic Scholar 论文搜索客户端
专门用于关键词搜索论文（非引用数据）
API 文档: https://api.semanticscholar.org/api-docs

@author Color2333
"""

from __future__ import annotations

import logging
import time
from contextlib import suppress
from datetime import date

import httpx

from packages.domain.schemas import PaperCreate

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.semanticscholar.org/graph/v1"
_MAX_RETRIES = 3
_RETRY_DELAY = 1.0


class SemanticScholarSearchClient:
    """
    Semantic Scholar 论文搜索 API 封装

    特性:
    - 关键词搜索论文
    - AI 增强数据（influential citations, TL;DR）
    - 复用连接
    - 429 自动重试
    - 返回 PaperCreate 格式

    使用示例:
    ```python
    client = SemanticScholarSearchClient()
    papers = client.search_papers("machine learning", max_results=10)
    ```
    """

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key
        self._client: httpx.Client | None = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            headers = {}
            if self.api_key:
                headers["x-api-key"] = self.api_key
            self._client = httpx.Client(
                base_url=_BASE_URL,
                timeout=20,
                follow_redirects=True,
                headers=headers,
            )
        return self._client

    def _get(self, path: str, params: dict | None = None) -> dict | None:
        for attempt in range(_MAX_RETRIES):
            try:
                resp = self.client.get(path, params=params)
                if resp.status_code == 429:
                    delay = _RETRY_DELAY * (2**attempt)
                    logger.warning(
                        "Semantic Scholar 429, retry %d/%d in %.1fs",
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
                logger.warning("Semantic Scholar timeout for %s, retry %d", path, attempt + 1)
                time.sleep(_RETRY_DELAY)
            except Exception as exc:
                logger.warning("Semantic Scholar error for %s: %s", path, exc)
                return None
        logger.error("Semantic Scholar exhausted retries for %s", path)
        return None

    def search_papers(
        self,
        query: str,
        max_results: int = 20,
        year: int | None = None,
    ) -> list[PaperCreate]:
        """
        搜索 Semantic Scholar 论文

        Args:
            query: 搜索关键词
            max_results: 最大结果数（默认 20）
            year: 出版年份（可选）

        Returns:
            list[PaperCreate]: 论文列表
        """
        params = {
            "query": query,
            "limit": min(max_results, 100),
            "fields": "paperId,title,abstract,authors,year,venue,citationCount,influentialCitationCount,externalIds,tldr",
        }

        if year:
            params["year"] = str(year)

        logger.info("Semantic Scholar 搜索: %s (max=%d)", query, max_results)

        data = self._get("/paper/search", params=params)
        if not data or "data" not in data:
            logger.warning("Semantic Scholar 搜索无结果: %s", query)
            return []

        papers = []
        for item in data["data"]:
            paper = self._parse_paper(item)
            if paper:
                papers.append(paper)

        logger.info("Semantic Scholar 搜索完成: %d 篇论文", len(papers))
        return papers

    def _parse_paper(self, item: dict) -> PaperCreate | None:
        """解析 Semantic Scholar 响应为 PaperCreate"""
        title = (item.get("title") or "").strip()
        if not title:
            return None

        abstract = item.get("abstract") or ""
        tldr = item.get("tldr")
        if tldr and isinstance(tldr, dict):
            tldr_text = tldr.get("text")
            if tldr_text:
                abstract = f"[TL;DR] {tldr_text}\n\n{abstract}"

        year = item.get("year")
        pub_date = None
        if year:
            with suppress(ValueError, TypeError):
                pub_date = date(year, 1, 1)

        authors = []
        for auth in item.get("authors", [])[:10]:
            name = (auth.get("name") or "").strip()
            if name:
                authors.append(name)

        venue = item.get("venue")

        external_ids = item.get("externalIds") or {}
        arxiv_id = external_ids.get("ArXiv")
        doi = external_ids.get("DOI")
        paper_id = item.get("paperId")

        metadata = {
            "source": "semantic_scholar",
            "scholar_paper_id": paper_id,
            "arxiv_id": arxiv_id,
            "doi": doi,
            "authors": authors,
            "venue": venue,
            "citation_count": item.get("citationCount"),
            "influential_citation_count": item.get("influentialCitationCount"),
        }

        return PaperCreate(
            source="semantic_scholar",
            source_id=paper_id,
            doi=doi,
            arxiv_id=arxiv_id,
            title=title,
            abstract=abstract,
            publication_date=pub_date,
            metadata=metadata,
        )

    def close(self) -> None:
        if self._client and not self._client.is_closed:
            self._client.close()

    def __del__(self) -> None:
        self.close()
