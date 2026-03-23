"""
OpenAlex 渠道适配器
将 OpenAlexSearchClient 适配到 ChannelBase 接口

@author Color2333
"""

from packages.domain.schemas import PaperCreate
from packages.integrations.channel_base import ChannelBase
from packages.integrations.openalex_search_client import OpenAlexSearchClient


class OpenAlexSearchChannel(ChannelBase):
    """
    OpenAlex 渠道适配器

    特性:
    - 全学科论文搜索（2.5亿+ 论文）
    - 支持年份过滤
    - 不支持 PDF 下载
    - 支持增量抓取（按出版年份）

    使用示例:
    ```python
    channel = OpenAlexSearchChannel()
    papers = channel.fetch("machine learning", max_results=20)
    ```
    """

    def __init__(self, email: str | None = None) -> None:
        self._client = OpenAlexSearchClient(email=email)

    @property
    def name(self) -> str:
        return "openalex"

    def fetch(self, query: str, max_results: int = 20) -> list[PaperCreate]:
        """从 OpenAlex 搜索论文"""
        return self._client.search_papers(query, max_results)

    def download_pdf(self, paper_id: str) -> str | None:
        """OpenAlex 不提供 PDF 下载，返回 None"""
        return None

    def supports_incremental(self) -> bool:
        """OpenAlex 支持按出版年份增量抓取"""
        return True
