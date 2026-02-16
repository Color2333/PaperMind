from __future__ import annotations

import logging
import re
import time
from datetime import date, datetime
from xml.etree import ElementTree

import httpx

from packages.config import get_settings
from packages.domain.schemas import PaperCreate

ARXIV_API_URL = "https://export.arxiv.org/api/query"
logger = logging.getLogger(__name__)


def _build_arxiv_query(raw: str) -> str:
    """将用户输入转换为 ArXiv API 查询语法

    - 已是结构化查询（含 all:/ti: 等）直接返回
    - 否则按空格拆分，取前 3 个关键词用 AND 连接（避免 429）
    """
    raw = raw.strip()
    if not raw:
        return raw
    if re.search(r'\b(all|ti|au|abs|cat|co|jr|rn|id):', raw):
        return raw
    # 拆分词汇，跳过短词（<2字符），最多取 3 个
    tokens = [t.strip() for t in raw.split() if len(t.strip()) >= 2]
    if not tokens:
        return f"all:{raw}"
    tokens = tokens[:3]
    return " AND ".join(f"all:{t}" for t in tokens)


class ArxivClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    def fetch_latest(self, query: str, max_results: int = 20) -> list[PaperCreate]:
        structured_query = _build_arxiv_query(query)
        logger.info("ArXiv search: %s → %s", query, structured_query)
        params = {
            "search_query": structured_query,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
            "start": 0,
            "max_results": max_results,
        }
        # 自动重试（429 限流 + 网络抖动）
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                with httpx.Client(timeout=60, follow_redirects=True) as client:
                    response = client.get(ARXIV_API_URL, params=params)
                    response.raise_for_status()
                return self._parse_atom(response.text)
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if exc.response.status_code == 429:
                    wait = 3 * (attempt + 1)
                    logger.warning("ArXiv 429 限流，等待 %ds 重试...", wait)
                    time.sleep(wait)
                    continue
                raise
            except httpx.TimeoutException as exc:
                last_exc = exc
                logger.warning("ArXiv 请求超时 (attempt %d)", attempt + 1)
                time.sleep(2)
                continue
        raise last_exc or RuntimeError("ArXiv fetch failed")

    def download_pdf(self, arxiv_id: str) -> str:
        url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
        target = self.settings.pdf_storage_root / f"{arxiv_id}.pdf"
        target.parent.mkdir(parents=True, exist_ok=True)
        with httpx.Client(timeout=90, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
            target.write_bytes(response.content)
        return str(target)

    def _parse_atom(self, payload: str) -> list[PaperCreate]:
        root = ElementTree.fromstring(payload)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        papers: list[PaperCreate] = []
        for entry in root.findall("atom:entry", ns):
            id_text = self._text(entry, "atom:id", ns)
            if not id_text:
                continue
            arxiv_id = id_text.rsplit("/", 1)[-1]
            title = self._text(entry, "atom:title", ns).replace("\n", " ").strip()
            summary = self._text(entry, "atom:summary", ns).strip()
            published_raw = self._text(entry, "atom:published", ns)
            published: date | None = None
            if published_raw:
                published = datetime.fromisoformat(published_raw.replace("Z", "+00:00")).date()

            # 解析 ArXiv categories（如 cs.CV, cs.LG, stat.ML）
            categories: list[str] = []
            for cat_el in entry.findall("atom:category", ns):
                term = cat_el.get("term")
                if term:
                    categories.append(term)

            # 解析作者列表
            authors: list[str] = []
            for author_el in entry.findall("atom:author", ns):
                name = self._text(author_el, "atom:name", ns)
                if name:
                    authors.append(name)

            papers.append(
                PaperCreate(
                    arxiv_id=arxiv_id,
                    title=title,
                    abstract=summary,
                    publication_date=published,
                    metadata={
                        "source": "arxiv",
                        "categories": categories,
                        "authors": authors,
                        "primary_category": categories[0] if categories else None,
                    },
                )
            )
        return papers

    @staticmethod
    def _text(entry: ElementTree.Element, path: str, ns: dict[str, str]) -> str:
        node = entry.find(path, ns)
        return node.text if node is not None and node.text else ""
