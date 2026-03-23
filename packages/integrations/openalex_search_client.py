"""
OpenAlex 论文搜索客户端
专门用于关键词搜索论文（非引用数据）
API 文档: https://docs.openalex.org/api/search-works

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

_BASE_URL = "https://api.openalex.org"
_MAX_RETRIES = 3
_RETRY_DELAY = 1.0


class OpenAlexSearchClient:
    """
    OpenAlex 论文搜索 API 封装

    特性:
    - 关键词搜索论文
    - 复用连接
    - 429 自动重试
    - 返回 PaperCreate 格式

    使用示例:
    ```python
    client = OpenAlexSearchClient(email="your@email.com")
    papers = client.search_papers("machine learning", max_results=10)
    ```
    """

    def __init__(self, email: str | None = None) -> None:
        self.email = email or "papermind@example.com"
        self._client: httpx.Client | None = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(
                base_url=_BASE_URL,
                timeout=20,
                follow_redirects=True,
            )
        return self._client

    def _get(self, path: str, params: dict | None = None) -> dict | None:
        params = dict(params or {})
        if self.email:
            params["mailto"] = self.email
        for attempt in range(_MAX_RETRIES):
            try:
                resp = self.client.get(path, params=params)
                if resp.status_code == 429:
                    delay = _RETRY_DELAY * (2**attempt)
                    logger.warning(
                        "OpenAlex 429, retry %d/%d in %.1fs", attempt + 1, _MAX_RETRIES, delay
                    )
                    time.sleep(delay)
                    continue
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                return resp.json()
            except httpx.TimeoutException:
                logger.warning("OpenAlex timeout for %s, retry %d", path, attempt + 1)
                time.sleep(_RETRY_DELAY)
            except Exception as exc:
                logger.warning("OpenAlex error for %s: %s", path, exc)
                return None
        logger.error("OpenAlex exhausted retries for %s", path)
        return None

    def search_papers(
        self,
        query: str,
        max_results: int = 20,
        start_year: int | None = None,
        end_year: int | None = None,
    ) -> list[PaperCreate]:
        """
        搜索 OpenAlex 论文

        Args:
            query: 搜索关键词
            max_results: 最大结果数（默认 20）
            start_year: 起始年份（可选）
            end_year: 结束年份（可选）

        Returns:
            list[PaperCreate]: 论文列表
        """
        params: dict = {
            "search": query,
            "per_page": min(max_results, 100),
        }

        if start_year or end_year:
            year_filter = []
            if start_year:
                year_filter.append(f"from_publication_year:{start_year}")
            if end_year:
                year_filter.append(f"to_publication_year:{end_year}")
            params["filter"] = ",".join(year_filter)

        params["select"] = (
            "id,title,display_name,abstract_inverted_index,authorships,publication_year,primary_location,type,cited_by_count,doi"
        )

        logger.info("OpenAlex 搜索: %s (max=%d)", query, max_results)

        data = self._get("/works", params=params)
        if not data or "results" not in data:
            logger.warning("OpenAlex 搜索无结果: %s", query)
            return []

        papers = []
        for work in data["results"]:
            paper = self._parse_work(work)
            if paper:
                papers.append(paper)

        logger.info("OpenAlex 搜索完成: %d 篇论文", len(papers))
        return papers

    def _parse_work(self, work: dict) -> PaperCreate | None:
        """解析 OpenAlex Work 为 PaperCreate"""
        title = (work.get("title") or work.get("display_name") or "").strip()
        if not title:
            return None

        abstract = None
        inv_idx = work.get("abstract_inverted_index")
        if inv_idx and isinstance(inv_idx, dict):
            abstract = _reconstruct_abstract(inv_idx)

        pub_year = work.get("publication_year")
        pub_date = None
        if pub_year:
            with suppress(ValueError, TypeError):
                pub_date = date(pub_year, 1, 1)

        authors = []
        for auth in work.get("authorships", [])[:10]:
            author = auth.get("author")
            if author:
                name = author.get("display_name") or ""
                if name:
                    authors.append(name)

        location = work.get("primary_location") or {}
        source = location.get("source") or {}
        venue = source.get("display_name") if source else None

        doi = work.get("doi")
        if doi:
            doi = doi.replace("https://doi.org/", "").strip()

        openalex_id = work.get("id", "").replace("https://openalex.org/", "").strip()

        metadata = {
            "source": "openalex",
            "openalex_id": openalex_id,
            "doi": doi,
            "authors": authors,
            "venue": venue,
            "type": work.get("type"),
            "cited_by_count": work.get("cited_by_count"),
            "openalex_url": work.get("id"),
        }

        return PaperCreate(
            source="openalex",
            source_id=openalex_id,
            doi=doi,
            arxiv_id=None,
            title=title,
            abstract=abstract or "",
            publication_date=pub_date,
            metadata=metadata,
        )

    def close(self) -> None:
        if self._client and not self._client.is_closed:
            self._client.close()

    def __del__(self) -> None:
        self.close()


def _reconstruct_abstract(inverted_index: dict) -> str:
    """从倒排索引重建摘要文本"""
    if not inverted_index:
        return ""
    word_positions: list[tuple[int, str]] = []
    for word, positions in inverted_index.items():
        for pos in positions:
            word_positions.append((pos, word))
    word_positions.sort()
    return " ".join(w for _, w in word_positions)
