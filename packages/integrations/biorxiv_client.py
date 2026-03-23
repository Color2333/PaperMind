"""
bioRxiv / medRxiv API 客户端
预印本论文搜索
API 文档: https://api.biorxiv.org/

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

_BIORXIV_BASE = "https://api.biorxiv.org/details/biorxiv"
_MEDRXIV_BASE = "https://api.biorxiv.org/details/medrxiv"
_MAX_RETRIES = 3
_RETRY_DELAY = 1.0


class BiorxivClient:
    """
    bioRxiv/medRxiv 预印本搜索 API 封装

    特性:
    - 预印本论文搜索（生物学/医学）
    - 支持日期范围搜索
    - 不支持 PDF 下载
    - 支持增量抓取

    使用示例:
    ```python
    client = BiorxivClient()
    papers = client.search_papers("CRISPR", max_results=10)
    ```
    """

    def __init__(self) -> None:
        self._client: httpx.Client | None = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(
                timeout=20,
                follow_redirects=True,
            )
        return self._client

    def _get(self, url: str, params: dict | None = None) -> dict | None:
        for attempt in range(_MAX_RETRIES):
            try:
                resp = self.client.get(url, params=params)
                if resp.status_code == 429:
                    delay = _RETRY_DELAY * (2**attempt)
                    logger.warning(
                        "bioRxiv 429, retry %d/%d in %.1fs", attempt + 1, _MAX_RETRIES, delay
                    )
                    time.sleep(delay)
                    continue
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                return resp.json()
            except httpx.TimeoutException:
                logger.warning("bioRxiv timeout for %s, retry %d", url, attempt + 1)
                time.sleep(_RETRY_DELAY)
            except Exception as exc:
                logger.warning("bioRxiv error for %s: %s", url, exc)
                return None
        logger.error("bioRxiv exhausted retries for %s", url)
        return None

    def search_papers(
        self,
        query: str,
        max_results: int = 20,
        server: str = "biorxiv",
        days_back: int = 30,
    ) -> list[PaperCreate]:
        """
        搜索预印本论文

        Args:
            query: 搜索关键词
            max_results: 最大结果数（默认 20）
            server: 服务器选择，"biorxiv" 或 "medrxiv"
            days_back: 搜索最近多少天的论文（默认 30）

        Returns:
            list[PaperCreate]: 论文列表
        """
        from datetime import date, timedelta

        today = date.today()
        start = today - timedelta(days=days_back)

        base_url = _BIORXIV_BASE if server == "biorxiv" else _MEDRXIV_BASE
        url = f"{base_url}/{start}/{today}"

        logger.info(
            "bioRxiv 搜索: %s (max=%d, server=%s, days=%d)", query, max_results, server, days_back
        )

        data = self._get(url, params={"format": "json"})
        if not data or "collection" not in data:
            logger.warning("bioRxiv 搜索无结果: %s", query)
            return []

        collection = data["collection"]

        papers = []
        query_lower = query.lower()

        for item in collection:
            title = (item.get("title") or "").strip().lower()
            abstract = (item.get("abstract") or "").strip().lower()

            if query_lower not in title and query_lower not in abstract:
                continue

            paper = self._parse_item(item, server)
            if paper:
                papers.append(paper)

            if len(papers) >= max_results:
                break

        logger.info("bioRxiv 搜索完成: %d 篇论文", len(papers))
        return papers

    def _parse_item(self, item: dict, server: str) -> PaperCreate | None:
        """解析预印本响应为 PaperCreate"""
        title = (item.get("title") or "").strip()
        if not title:
            return None

        abstract = (item.get("abstract") or "").strip()

        doi = item.get("doi")
        if not doi:
            return None

        authors_str = item.get("authors", "")
        authors = [a.strip() for a in authors_str.split(";")][:10] if authors_str else []

        category = item.get("category", "")

        published_str = item.get("published")
        pub_date = None
        if published_str:
            with suppress(ValueError, TypeError):
                pub_date = date.fromisoformat(published_str[:10])

        version = item.get("version", "1")

        metadata = {
            "source": server,
            "doi": doi,
            "authors": authors,
            "category": category,
            "version": version,
            "server": server,
            "biorxiv_url": f"https://{server}.org/doi/{doi}",
        }

        source_id = f"{server}:{doi}"

        return PaperCreate(
            source=server,
            source_id=source_id,
            doi=doi,
            arxiv_id=None,
            title=title,
            abstract=abstract,
            publication_date=pub_date,
            metadata=metadata,
        )

    def get_recent(
        self,
        days: int = 7,
        max_results: int = 20,
        server: str = "biorxiv",
    ) -> list[PaperCreate]:
        """
        获取最近 N 天的预印本

        Args:
            days: 最近天数（默认 7）
            max_results: 最大结果数（默认 20）
            server: 服务器选择，"biorxiv" 或 "medrxiv"

        Returns:
            list[PaperCreate]: 论文列表
        """
        base_url = _BIORXIV_BASE if server == "biorxiv" else _MEDRXIV_BASE

        params = {
            "format": "json",
        }

        logger.info("bioRxiv 获取最近 %d 天: server=%s", days, server)

        data = self._get(base_url, params=params)
        if not data or "collection" not in data:
            logger.warning("bioRxiv 获取最近无结果")
            return []

        collection = data["collection"]

        papers = []
        for item in collection[:max_results]:
            paper = self._parse_item(item, server)
            if paper:
                papers.append(paper)

        logger.info("bioRxiv 获取最近完成: %d 篇论文", len(papers))
        return papers

    def close(self) -> None:
        if self._client and not self._client.is_closed:
            self._client.close()

    def __del__(self) -> None:
        self.close()
