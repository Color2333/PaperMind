from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ElementTree
from datetime import date, datetime, timedelta

import httpx

from packages.ai.rate_limiter import acquire_api, record_rate_limit_error
from packages.config import get_settings
from packages.domain.schemas import PaperCreate

ARXIV_API_URL = "https://export.arxiv.org/api/query"
logger = logging.getLogger(__name__)


def _build_arxiv_query(raw: str, days_back: int = 0) -> str:
    """将用户输入转换为 ArXiv API 查询语法

    - 已是结构化查询（含 all:/ti: 等）直接返回
    - 带引号则识别为精确短语搜索
    - 否则按空格拆分，取前 6 个关键词用 AND 连接
    - 当 days_back > 0 时自动添加最近 N 天的日期范围过滤（默认 0 = 不过滤）
    """
    raw = raw.strip()
    if not raw:
        return raw
    date_filter = ""
    if days_back > 0:
        from_date = datetime.now() - timedelta(days=days_back)
        date_filter = f" AND submittedDate:[{from_date.strftime('%Y%m%d')}000000 TO *]"

    if re.search(r"\b(all|ti|au|abs|cat|co|jr|rn|id):", raw):
        if "submittedDate:" not in raw:
            return raw + date_filter
        return raw

    # 整串带引号 → 当作精确短语搜索
    quoted = re.match(r'^"(.+)"$', raw)
    if quoted:
        phrase = quoted.group(1).strip()
        return f'all:"{phrase}"' + date_filter

    # 拆词：跳过短词（<2 字符），最多取 6 个（原为 3，易把多关键词查询截断）
    tokens = [t.strip() for t in raw.split() if len(t.strip()) >= 2]
    if not tokens:
        return f"all:{raw}"
    tokens = tokens[:6]
    return " AND ".join(f"all:{t}" for t in tokens) + date_filter


class ArxivClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client: httpx.Client | None = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(timeout=60, follow_redirects=True)
        return self._client

    def fetch_latest(
        self,
        query: str,
        max_results: int = 20,
        sort_by: str = "submittedDate",
        start: int = 0,
        days_back: int = 0,
    ) -> list[PaperCreate]:
        """sort_by: submittedDate(最新) / relevance(相关性) / lastUpdatedDate

        days_back 默认 0 = 不加日期过滤（否则经典老论文如 OpenShape/Uni3D 都会被筛掉）。
        订阅/定时任务需要最新增量时，由调用方显式传 days_back。
        """
        # 获取速率限制许可（10 秒超时）
        if not acquire_api("arxiv", timeout=10.0):
            raise httpx.TimeoutException("ArXiv 速率限制等待超时，请稍后重试")

        structured_query = _build_arxiv_query(query, days_back)
        logger.info(
            "ArXiv search: %s → %s (sort=%s start=%d days_back=%d)",
            query,
            structured_query,
            sort_by,
            start,
            days_back,
        )
        params = {
            "search_query": structured_query,
            "sortBy": sort_by,
            "sortOrder": "descending",
            "start": start,
            "max_results": max_results,
        }
        # 自动重试（429 限流 + 网络抖动 + 500 回退）
        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                response = self.client.get(ARXIV_API_URL, params=params)
                response.raise_for_status()
                return self._parse_atom(response.text)
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                status = exc.response.status_code
                if status == 429:
                    record_rate_limit_error("arxiv")
                    wait = 3 * (attempt + 1)
                    logger.warning("ArXiv 429 限流，等待 %ds 重试...", wait)
                    time.sleep(wait)
                    continue
                elif status == 500 and "submittedDate:" in structured_query:
                    # arXiv API 日期过滤可能有问题，尝试不带日期的查询
                    logger.warning("ArXiv 500 错误（可能是日期过滤问题），尝试不带日期的查询")
                    simple_query = _build_arxiv_query(query, days_back=0)  # 不添加日期
                    params["search_query"] = simple_query
                    response = self.client.get(ARXIV_API_URL, params=params)
                    response.raise_for_status()
                    return self._parse_atom(response.text)
                raise
            except httpx.TimeoutException as exc:
                last_exc = exc
                logger.warning("ArXiv 请求超时 (attempt %d)", attempt + 1)
                time.sleep(2)
                continue
        raise last_exc or RuntimeError("ArXiv fetch failed")

    def fetch_by_ids(self, arxiv_ids: list[str]) -> list[PaperCreate]:
        """按 arXiv ID 列表批量获取论文元数据"""
        if not arxiv_ids:
            return []
        clean_ids = [aid.split("v")[0] if "v" in aid else aid for aid in arxiv_ids]
        id_list = ",".join(clean_ids)
        params = {"id_list": id_list, "max_results": len(clean_ids)}

        # 获取速率限制许可（10 秒超时）
        if not acquire_api("arxiv", timeout=10.0):
            raise httpx.TimeoutException("ArXiv 速率限制等待超时，请稍后重试")

        last_exc: Exception | None = None
        for attempt in range(3):
            try:
                resp = self.client.get(ARXIV_API_URL, params=params)
                resp.raise_for_status()
                return self._parse_atom(resp.text)
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if exc.response.status_code == 429:
                    record_rate_limit_error("arxiv")
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
        raise last_exc or RuntimeError("ArXiv fetch_by_ids failed")

    def download_pdf(self, arxiv_id: str) -> str:
        """下载 PDF 到本地存储"""
        url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
        target = self.settings.pdf_storage_root / f"{arxiv_id}.pdf"
        target.parent.mkdir(parents=True, exist_ok=True)

        # PDF 下载不经过速率限制器（因为是直接下载，不是 API 查询）
        response = self.client.get(url, timeout=90)
        response.raise_for_status()
        target.write_bytes(response.content)
        return str(target)

    def fetch_categories(self) -> list[dict]:
        """从 arXiv API 获取 CS 分类列表，失败时返回常用 CS 分类"""
        FALLBACK_CS_CATEGORIES = [
            {"code": "cs.CV", "name": "Computer Vision and Pattern Recognition", "description": ""},
            {"code": "cs.LG", "name": "Machine Learning", "description": ""},
            {"code": "cs.CL", "name": "Computation and Language", "description": ""},
            {"code": "cs.AI", "name": "Artificial Intelligence", "description": ""},
            {"code": "cs.NE", "name": "Neural and Evolutionary Computing", "description": ""},
            {"code": "cs.IR", "name": "Information Retrieval", "description": ""},
            {"code": "cs.IT", "name": "Information Theory", "description": ""},
            {"code": "cs.CR", "name": "Cryptography and Security", "description": ""},
            {"code": "cs.DS", "name": "Data Structures and Algorithms", "description": ""},
            {"code": "cs.DB", "name": "Databases", "description": ""},
            {"code": "cs.DC", "name": "Distributed Computing", "description": ""},
            {"code": "cs.SE", "name": "Software Engineering", "description": ""},
            {"code": "cs.PL", "name": "Programming Languages", "description": ""},
            {"code": "cs.HC", "name": "Human-Computer Interaction", "description": ""},
            {"code": "cs.GR", "name": "Graphics", "description": ""},
            {"code": "cs.RO", "name": "Robotics", "description": ""},
            {"code": "cs.CY", "name": "Computers and Society", "description": ""},
            {"code": "cs.SI", "name": "Social and Information Networks", "description": ""},
            {"code": "cs.MA", "name": "Multiagent Systems", "description": ""},
            {"code": "cs.MM", "name": "Multimedia", "description": ""},
            {"code": "cs.OH", "name": "Other", "description": ""},
            {"code": "cs.CC", "name": "Computational Complexity", "description": ""},
            {"code": "cs.CE", "name": "Computational Engineering", "description": ""},
            {"code": "cs.GT", "name": "Game Theory", "description": ""},
            {"code": "cs.AR", "name": "Hardware and Architecture", "description": ""},
        ]
        try:
            url = "https://arxiv.org/api/categories"
            acquire_api("arxiv", timeout=30)
            response = self.client.get(url, timeout=30)
            response.raise_for_status()
            root = ElementTree.fromstring(response.text)
            categories = []
            for cat in root.findall("category"):
                code = cat.find("code").text or ""
                if code.startswith("cs."):
                    categories.append(
                        {
                            "code": code,
                            "name": cat.find("name").text or "",
                            "description": cat.find("description").text or "",
                        }
                    )
            return categories
        except Exception:
            logger.warning("Failed to fetch categories from arXiv API, using fallback")
            return FALLBACK_CS_CATEGORIES

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
