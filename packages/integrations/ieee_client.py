"""
IEEE Xplore API 客户端
连接复用 + 429 重试 + 日志
注意：需要 API Key（免费版 50 次/天，付费版$129/月起）
文档：https://developer.ieee.org/docs

@author Color2333
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import Optional

import httpx

from packages.domain.schemas import PaperCreate
from packages.config import get_settings

logger = logging.getLogger(__name__)

IEEE_API_BASE = "https://ieeexploreapi.ieee.org/api/v1"
RETRY_CODES = {429, 500, 502, 503}
MAX_RETRIES = 3
BASE_DELAY = 2.0
MAX_DELAY = 15.0


@dataclass
class IeeePaperData:
    """IEEE 论文数据结构（内部使用）"""

    ieee_doc_id: str  # IEEE Document ID
    doi: str | None
    title: str
    abstract: str
    authors: list[str]
    publication_date: date | None
    venue: str | None  # 期刊/会议名称
    publisher: str
    isbn: str | None
    issn: str | None
    pdf_available: bool = False


class IeeeClient:
    """
    IEEE Xplore REST API 封装

    特性:
    - httpx.Client 连接复用
    - 429/500 错误自动重试（指数退避）
    - 详细日志记录
    - 支持关键词搜索、DOI 查询、元数据获取

    使用示例:
    ```python
    client = IeeeClient(api_key="your_key")
    papers = client.fetch_by_keywords("machine learning", max_results=10)
    ```
    """

    def __init__(self, api_key: str | None = None) -> None:
        """
        初始化 IEEE 客户端

        Args:
            api_key: IEEE API Key（可选，默认从环境变量读取）
        """
        settings = get_settings()
        self.api_key = api_key or os.getenv("IEEE_API_KEY")
        self._client: httpx.Client | None = None

        if not self.api_key:
            logger.warning("IEEE API Key 未配置，IEEE 功能将不可用")

    @property
    def client(self) -> httpx.Client:
        """复用 httpx.Client 连接池"""
        if self._client is None or self._client.is_closed:
            headers = {}
            if self.api_key:
                headers["apikey"] = self.api_key

            self._client = httpx.Client(
                base_url=IEEE_API_BASE,
                timeout=20,
                headers=headers,
                follow_redirects=True,
            )
            logger.info("IEEE Client 初始化完成")
        return self._client

    def _get(self, path: str, params: dict | None = None) -> dict | None:
        """
        带重试的 GET 请求

        重试策略:
        - 429/500/502/503 错误自动重试
        - 指数退避：2s, 4s, 8s, ... 最长 15s
        - 最多重试 3 次

        Args:
            path: API 路径
            params: 查询参数

        Returns:
            响应 JSON 数据，失败返回 None
        """
        for attempt in range(MAX_RETRIES):
            try:
                resp = self.client.get(path, params=params)

                if resp.status_code in RETRY_CODES:
                    delay = min(BASE_DELAY * (2**attempt), MAX_DELAY)
                    logger.warning(
                        "IEEE API %d for %s, retry %d/%d in %.1fs",
                        resp.status_code,
                        path,
                        attempt + 1,
                        MAX_RETRIES,
                        delay,
                    )
                    time.sleep(delay)
                    continue

                if resp.status_code == 404:
                    logger.info("IEEE API 404: %s", path)
                    return None

                if resp.status_code == 403:
                    logger.error("IEEE API 403: 权限不足或 API Key 无效")
                    return None

                resp.raise_for_status()
                return resp.json()

            except httpx.TimeoutException:
                logger.warning("IEEE API timeout for %s, retry %d", path, attempt + 1)
                time.sleep(BASE_DELAY)
            except httpx.HTTPError as exc:
                logger.warning("IEEE API HTTP error for %s: %s", path, exc)
                return None
            except Exception as exc:
                logger.warning("IEEE API error for %s: %s", path, exc)
                return None

        logger.error("IEEE API exhausted retries for %s", path)
        return None

    def fetch_by_keywords(
        self,
        query: str,
        max_results: int = 20,
        start_year: int | None = None,
        end_year: int | None = None,
    ) -> list[PaperCreate]:
        """
        按关键词搜索 IEEE 论文

        Args:
            query: 搜索关键词
            max_results: 最大结果数（1-200，默认 20）
            start_year: 起始年份（可选）
            end_year: 结束年份（可选）

        Returns:
            list[PaperCreate]: 论文元数据列表

        示例:
        ```python
        client = IeeeClient(api_key="xxx")
        papers = client.fetch_by_keywords(
            "deep learning",
            max_results=10,
            start_year=2023,
            end_year=2024
        )
        ```
        """
        if not self.api_key:
            logger.warning("IEEE API Key 未配置，无法执行搜索")
            return []

        # 构建查询参数
        params = {
            "querytext": query,
            "max_records": min(max_results, 200),
            "start_record": 1,
        }

        if start_year:
            params["start_year"] = start_year
        if end_year:
            params["end_year"] = end_year

        logger.info(
            "IEEE 搜索：%s (max=%d, year=%s-%s)",
            query,
            max_results,
            start_year,
            end_year,
        )

        data = self._get("/search", params=params)
        if not data or "articles" not in data:
            logger.warning("IEEE 搜索无结果：%s", query)
            return []

        papers = []
        for article in data["articles"]:
            paper = self._parse_article(article)
            if paper:
                papers.append(paper)

        logger.info(
            "IEEE 搜索完成：%d 篇论文（从 %d 篇中筛选）", len(papers), len(data["articles"])
        )
        return papers

    def fetch_by_doi(self, doi: str) -> PaperCreate | None:
        """
        按 DOI 获取 IEEE 论文元数据

        Args:
            doi: DOI 号（如 "10.1109/CVPR52729.2023.00001"）

        Returns:
            PaperCreate | None: 论文元数据或 None
        """
        if not self.api_key:
            logger.warning("IEEE API Key 未配置")
            return None

        clean_doi = doi.replace("doi/", "").strip()
        logger.info("IEEE 按 DOI 查询：%s", clean_doi)

        data = self._get(f"/articles/{clean_doi}")
        if not data:
            logger.info("IEEE DOI 查询无结果：%s", doi)
            return None

        return self._parse_article(data)

    def fetch_metadata(self, ieee_doc_id: str) -> PaperCreate | None:
        """
        按 IEEE Document ID 获取元数据

        Args:
            ieee_doc_id: IEEE Document ID（如 "10185093"）

        Returns:
            PaperCreate | None: 论文元数据或 None
        """
        if not self.api_key:
            logger.warning("IEEE API Key 未配置")
            return None

        logger.info("IEEE 按 ID 查询：%s", ieee_doc_id)
        data = self._get(f"/articles/{ieee_doc_id}")
        if not data:
            logger.info("IEEE ID 查询无结果：%s", ieee_doc_id)
            return None

        return self._parse_article(data)

    def download_pdf(self, ieee_doc_id: str) -> str | None:
        """
        下载 IEEE 论文 PDF（需要机构订阅）

        ⚠️ 注意：
        - 此方法可能失败（权限限制）
        - 需要机构订阅或付费购买
        - 目前仅返回 None，表示 PDF 不可用

        Args:
            ieee_doc_id: IEEE Document ID

        Returns:
            PDF 本地路径 或 None
        """
        logger.warning("IEEE PDF 下载需要机构订阅，暂不支持：%s", ieee_doc_id)
        # TODO: 未来可集成机构代理下载
        # IEEE PDF 下载需要额外的认证流程和机构订阅
        # 目前返回 None，上层逻辑应处理此情况
        return None

    def _parse_article(self, article: dict) -> PaperCreate | None:
        """
        解析 IEEE API 响应为 PaperCreate

        IEEE API 字段参考:
        https://developer.ieee.org/docs/read/REST_API_Fields

        Args:
            article: IEEE API 响应的 article 对象

        Returns:
            PaperCreate | None: 解析后的论文数据
        """
        # 提取 IEEE Document ID
        ieee_doc_id = str(article.get("article_number", ""))
        if not ieee_doc_id:
            logger.warning("IEEE article 缺少 article_number")
            return None

        # 提取 DOI
        doi = article.get("doi")

        # 提取标题
        title = (article.get("title") or "").strip()
        if not title:
            logger.warning("IEEE article 缺少标题：%s", ieee_doc_id)
            return None

        # 提取摘要
        abstract = ""
        if "abstract" in article:
            abstract = article["abstract"].strip()

        # 提取出版日期
        pub_date = None
        pub_date_str = article.get("publication_date")
        if pub_date_str:
            try:
                # IEEE 日期格式：2023-06-15 或 2023-06
                if len(pub_date_str) >= 10:
                    pub_date = date.fromisoformat(pub_date_str[:10])
                elif len(pub_date_str) >= 7:
                    pub_date = date.fromisoformat(pub_date_str[:7] + "-01")
            except (ValueError, TypeError) as exc:
                logger.warning("IEEE 出版日期解析失败：%s - %s", pub_date_str, exc)

        # 提取作者列表
        authors: list[str] = []
        for author in article.get("authors", []):
            if isinstance(author, dict):
                name = (author.get("full_name") or author.get("name") or "").strip()
                if name:
                    authors.append(name)

        # 提取期刊/会议名称
        venue = article.get("publication_title", "") or None
        if venue:
            venue = venue.strip()

        # 提取出版商
        publisher = article.get("publisher", "IEEE")

        # 提取 ISBN/ISSN
        isbn = article.get("isbn", None)
        issn = article.get("issn", None)

        # 检查 PDF 是否可用
        pdf_available = article.get("pdf_url") is not None

        # 构建 metadata（渠道特有字段）
        metadata = {
            "source": "ieee",
            "ieee_doc_id": ieee_doc_id,
            "doi": doi,
            "authors": authors,
            "venue": venue,
            "publisher": publisher,
            "isbn": isbn,
            "issn": issn,
            "pdf_available": pdf_available,
            # IEEE 特有字段
            "article_number": ieee_doc_id,
            "publication_year": article.get("publication_year"),
            "content_type": article.get("content_type"),  # Conference/Journal
        }

        # 构建 PaperCreate 对象
        return PaperCreate(
            source="ieee",
            source_id=ieee_doc_id,
            doi=doi,
            arxiv_id=None,  # IEEE 论文没有 arxiv_id
            title=title,
            abstract=abstract,
            publication_date=pub_date,
            metadata=metadata,
        )

    def close(self) -> None:
        """关闭 HTTP 客户端连接"""
        if self._client and not self._client.is_closed:
            self._client.close()
            logger.info("IEEE Client 连接已关闭")

    def __del__(self) -> None:
        """析构函数，确保连接关闭"""
        self.close()


# ========== 便捷函数 ==========


def create_ieee_client(api_key: str | None = None) -> IeeeClient:
    """
    创建 IEEE 客户端实例的便捷函数

    Args:
        api_key: IEEE API Key（可选）

    Returns:
        IeeeClient: 客户端实例
    """
    return IeeeClient(api_key=api_key)
