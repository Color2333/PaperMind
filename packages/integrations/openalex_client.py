"""
OpenAlex API 客户端
高速率引用数据源（10 req/s, 100k/day），覆盖 4.7 亿论文
@author Bamzc
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import httpx

from packages.integrations.semantic_scholar_client import (
    CitationEdge,
    RichCitationInfo,
)

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.openalex.org"
_MAX_RETRIES = 3
_RETRY_DELAY = 1.0


class OpenAlexClient:
    """OpenAlex REST API 封装，复用 CitationEdge/RichCitationInfo 数据结构"""

    def __init__(self, email: str | None = None) -> None:
        self.email = email
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
                    delay = _RETRY_DELAY * (2 ** attempt)
                    logger.warning("OpenAlex 429, retry %d/%d in %.1fs", attempt + 1, _MAX_RETRIES, delay)
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

    # ------------------------------------------------------------------
    # 论文查找
    # ------------------------------------------------------------------

    def _resolve_work(self, *, arxiv_id: str | None = None, title: str | None = None) -> dict | None:
        """通过 arXiv ID 或标题找到 OpenAlex Work"""
        if arxiv_id:
            clean = arxiv_id.split("v")[0] if "v" in arxiv_id else arxiv_id
            data = self._get(f"/works/https://arxiv.org/abs/{clean}")
            if data and data.get("id"):
                return data

        if title:
            data = self._get("/works", params={
                "filter": f'title.search:"{title[:200]}"',
                "per_page": 1,
                "select": "id,title,publication_year,cited_by_count,primary_location,referenced_works,related_works",
            })
            if data:
                results = data.get("results", [])
                if results:
                    return results[0]
        return None

    def _resolve_work_id(self, *, arxiv_id: str | None = None, title: str | None = None) -> str | None:
        work = self._resolve_work(arxiv_id=arxiv_id, title=title)
        if work:
            return work.get("id")
        return None

    # ------------------------------------------------------------------
    # 引用边（兼容 CitationEdge）
    # ------------------------------------------------------------------

    def fetch_edges_by_title(
        self, title: str, limit: int = 8, *, arxiv_id: str | None = None,
    ) -> list[CitationEdge]:
        work = self._resolve_work(arxiv_id=arxiv_id, title=title)
        if not work:
            return []

        work_id = work.get("id", "")
        edges: list[CitationEdge] = []

        # 参考文献（referenced_works 是 OpenAlex ID 列表）
        ref_ids = (work.get("referenced_works") or [])[:limit]
        if ref_ids:
            ref_works = self._fetch_works_by_ids(ref_ids)
            for rw in ref_works:
                t = (rw.get("title") or "").strip()
                if t:
                    edges.append(CitationEdge(source_title=title, target_title=t, context="reference"))

        # 被引用（cited_by → 用 filter 查询）
        cited_data = self._get("/works", params={
            "filter": f"cites:{work_id}",
            "per_page": min(limit, 50),
            "select": "id,title",
        })
        if cited_data:
            for cw in (cited_data.get("results") or [])[:limit]:
                t = (cw.get("title") or "").strip()
                if t:
                    edges.append(CitationEdge(source_title=t, target_title=title, context="citation"))

        return edges

    # ------------------------------------------------------------------
    # 丰富引用信息（兼容 RichCitationInfo）
    # ------------------------------------------------------------------

    def fetch_rich_citations(
        self,
        title: str,
        ref_limit: int = 30,
        cite_limit: int = 30,
        *,
        arxiv_id: str | None = None,
    ) -> list[RichCitationInfo]:
        work = self._resolve_work(arxiv_id=arxiv_id, title=title)
        if not work:
            return []

        work_id = work.get("id", "")
        results: list[RichCitationInfo] = []

        # 参考文献
        ref_ids = (work.get("referenced_works") or [])[:ref_limit]
        if ref_ids:
            ref_works = self._fetch_works_by_ids(ref_ids, detailed=True)
            for rw in ref_works:
                info = self._work_to_rich_info(rw, direction="reference")
                if info:
                    results.append(info)

        # 被引
        cited_data = self._get("/works", params={
            "filter": f"cites:{work_id}",
            "per_page": min(cite_limit, 50),
            "select": "id,title,publication_year,cited_by_count,primary_location,authorships,abstract_inverted_index",
        })
        if cited_data:
            for cw in (cited_data.get("results") or [])[:cite_limit]:
                info = self._work_to_rich_info(cw, direction="citation")
                if info:
                    results.append(info)

        return results

    # ------------------------------------------------------------------
    # 批量元数据（兼容 fetch_batch_metadata）
    # ------------------------------------------------------------------

    def fetch_batch_metadata(self, titles: list[str], max_papers: int = 10) -> list[dict]:
        results: list[dict] = []
        for title in titles[:max_papers]:
            work = self._resolve_work(title=title)
            if not work:
                continue
            venue = ""
            loc = work.get("primary_location") or {}
            src = loc.get("source") or {}
            if src:
                venue = src.get("display_name", "")
            results.append({
                "title": (work.get("title") or "").strip(),
                "year": work.get("publication_year"),
                "citationCount": work.get("cited_by_count"),
                "influentialCitationCount": None,
                "venue": venue or None,
                "fieldsOfStudy": [],
                "tldr": None,
            })
        return results

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------

    def _fetch_works_by_ids(self, openalex_ids: list[str], detailed: bool = False) -> list[dict]:
        """批量获取 works（OpenAlex 支持 filter 用 | 分隔多 ID）"""
        if not openalex_ids:
            return []

        # OpenAlex 的 filter 一次最多支持 ~50 个 ID
        all_works: list[dict] = []
        for i in range(0, len(openalex_ids), 50):
            batch = openalex_ids[i:i + 50]
            id_filter = "|".join(batch)
            select = "id,title,publication_year,cited_by_count,primary_location"
            if detailed:
                select += ",authorships,abstract_inverted_index"
            data = self._get("/works", params={
                "filter": f"openalex:{id_filter}",
                "per_page": 50,
                "select": select,
            })
            if data:
                all_works.extend(data.get("results") or [])
        return all_works

    @staticmethod
    def _work_to_rich_info(work: dict, direction: str) -> RichCitationInfo | None:
        title = (work.get("title") or "").strip()
        if not title:
            return None

        # 提取 arXiv ID
        arxiv_id = None
        loc = work.get("primary_location") or {}
        landing_url = loc.get("landing_page_url") or ""
        if "arxiv.org/abs/" in landing_url:
            arxiv_id = landing_url.split("arxiv.org/abs/")[-1].split("v")[0]

        # 提取摘要（OpenAlex 用倒排索引存储摘要）
        abstract = None
        inv_idx = work.get("abstract_inverted_index")
        if inv_idx and isinstance(inv_idx, dict):
            abstract = _reconstruct_abstract(inv_idx)[:500] if inv_idx else None

        # 提取 venue
        venue = None
        src = (loc.get("source") or {})
        if src:
            venue = src.get("display_name")

        return RichCitationInfo(
            scholar_id=work.get("id"),
            title=title,
            year=work.get("publication_year"),
            venue=venue,
            citation_count=work.get("cited_by_count"),
            arxiv_id=arxiv_id,
            abstract=abstract,
            direction=direction,
        )

    def close(self) -> None:
        if self._client and not self._client.is_closed:
            self._client.close()

    def __del__(self) -> None:
        self.close()


def _reconstruct_abstract(inverted_index: dict) -> str:
    """从 OpenAlex 的倒排索引重建摘要文本"""
    if not inverted_index:
        return ""
    word_positions: list[tuple[int, str]] = []
    for word, positions in inverted_index.items():
        for pos in positions:
            word_positions.append((pos, word))
    word_positions.sort()
    return " ".join(w for _, w in word_positions)
