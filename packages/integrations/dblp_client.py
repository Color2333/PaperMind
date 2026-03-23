"""
DBLP API 客户端
计算机科学会议论文搜索
API 文档: https://dblp.org/faq/How+can+I+fetch+DBLP+data.html

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

_BASE_URL = "https://api.crossref.org/works"
_MAX_RETRIES = 3
_RETRY_DELAY = 1.0


class DblpClient:
    """
    DBLP 论文搜索 API 封装

    DBLP 的计算机科学论文索引，支持会议和期刊论文搜索。
    使用 CrossRef API 作为后端（DBLP 数据通过 CrossRef 提供）。

    特性:
    - CS 会议/期刊论文搜索
    - 复用连接
    - 429 自动重试
    - 返回 PaperCreate 格式

    使用示例:
    ```python
    client = DblpClient()
    papers = client.search_papers("neural network", max_results=10)
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
                headers={"User-Agent": f"PaperMind/1.0 (mailto:{self.email})"},
            )
        return self._client

    def _get(self, path: str, params: dict | None = None) -> dict | None:
        params = dict(params or {})
        for attempt in range(_MAX_RETRIES):
            try:
                resp = self.client.get(path, params=params)
                if resp.status_code == 429:
                    delay = _RETRY_DELAY * (2**attempt)
                    logger.warning(
                        "DBLP 429, retry %d/%d in %.1fs", attempt + 1, _MAX_RETRIES, delay
                    )
                    time.sleep(delay)
                    continue
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                return resp.json()
            except httpx.TimeoutException:
                logger.warning("DBLP timeout for %s, retry %d", path, attempt + 1)
                time.sleep(_RETRY_DELAY)
            except Exception as exc:
                logger.warning("DBLP error for %s: %s", path, exc)
                return None
        logger.error("DBLP exhausted retries for %s", path)
        return None

    def search_papers(
        self,
        query: str,
        max_results: int = 20,
    ) -> list[PaperCreate]:
        """
        搜索 DBLP/CS 论文

        Args:
            query: 搜索关键词
            max_results: 最大结果数（默认 20）

        Returns:
            list[PaperCreate]: 论文列表
        """
        params = {
            "query": query,
            "rows": min(max_results, 100),
            "select": "DOI,title,abstract,author,published-print,published-online,type,container-title",
        }

        logger.info("DBLP 搜索: %s (max=%d)", query, max_results)

        data = self._get("", params=params)
        if not data or "message" not in data:
            logger.warning("DBLP 搜索无结果: %s", query)
            return []

        items = data["message"].get("items", [])
        papers = []
        for item in items:
            paper = self._parse_item(item)
            if paper:
                papers.append(paper)

        logger.info("DBLP 搜索完成: %d 篇论文", len(papers))
        return papers

    def _parse_item(self, item: dict) -> PaperCreate | None:
        """解析 CrossRef 响应为 PaperCreate"""
        title = (item.get("title") or [""])[0]
        if not title:
            return None

        abstract = None
        if "abstract" in item:
            abstract = (
                item["abstract"].replace("<jats:abstract>", "").replace("</jats:abstract>", "")
            )
            abstract = abstract.replace("<jats:p>", "").replace("</jats:p>", "").strip()

        pub_date = None
        pub_dates = item.get("published-print") or item.get("published-online") or {}
        date_parts = pub_dates.get("date-parts", [[]])
        if date_parts and date_parts[0]:
            parts = date_parts[0]
            if len(parts) >= 3:
                with suppress(ValueError, TypeError):
                    pub_date = date(parts[0], parts[1], parts[2])
            elif len(parts) >= 1:
                with suppress(ValueError, TypeError):
                    pub_date = date(parts[0], 1, 1)

        authors = []
        for auth in item.get("author", [])[:10]:
            name = (auth.get("given", "") + " " + auth.get("family", "")).strip()
            if name:
                authors.append(name)

        doi = item.get("DOI")
        container_titles = item.get("container-title", [])
        venue = container_titles[0] if container_titles else None

        paper_type = item.get("type")

        metadata = {
            "source": "dblp",
            "doi": doi,
            "authors": authors,
            "venue": venue,
            "type": paper_type,
            "dblp_url": f"https://dblp.org/doi/{doi}" if doi else None,
        }

        return PaperCreate(
            source="dblp",
            source_id=doi,
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
