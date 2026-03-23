"""
Semantic Scholar 渠道适配器
将 SemanticScholarSearchClient 适配到 ChannelBase 接口

@author Color2333
"""

from packages.domain.schemas import PaperCreate
from packages.integrations.channel_base import ChannelBase
from packages.integrations.semantic_scholar_search_client import SemanticScholarSearchClient


class SemanticScholarSearchChannel(ChannelBase):
    """
    Semantic Scholar 渠道适配器

    特性:
    - 全学科论文搜索（2亿+ 论文）
    - AI 增强数据（influential citations, TL;DR）
    - 不支持 PDF 下载
    - 支持增量抓取（按年份）

    使用示例:
    ```python
    channel = SemanticScholarSearchChannel()
    papers = channel.fetch("machine learning", max_results=20)
    ```
    """

    def __init__(self, api_key: str | None = None) -> None:
        self._client = SemanticScholarSearchClient(api_key=api_key)

    @property
    def name(self) -> str:
        return "semantic_scholar"

    def fetch(self, query: str, max_results: int = 20) -> list[PaperCreate]:
        """从 Semantic Scholar 搜索论文"""
        return self._client.search_papers(query, max_results)

    def download_pdf(self, paper_id: str) -> str | None:
        """Semantic Scholar 不提供 PDF 下载，返回 None"""
        return None

    def supports_incremental(self) -> bool:
        """Semantic Scholar 支持按年份增量抓取"""
        return True
