"""
ArXiv 渠道适配器
将现有 ArXiv 客户端适配到 ChannelBase 接口

@author Color2333
"""

from packages.integrations.arxiv_client import ArxivClient
from packages.integrations.channel_base import ChannelBase
from packages.domain.schemas import PaperCreate


class ArxivChannel(ChannelBase):
    """
    ArXiv 渠道适配器

    特性:
    - 复用现有 ArxivClient
    - 统一设置 source 字段
    - 支持增量抓取（按提交日期）

    使用示例:
    ```python
    channel = ArxivChannel()
    papers = channel.fetch("deep learning", max_results=20)
    ```
    """

    def __init__(self) -> None:
        self._client = ArxivClient()

    @property
    def name(self) -> str:
        return "arxiv"

    def fetch(self, query: str, max_results: int = 20) -> list[PaperCreate]:
        """
        从 ArXiv 搜索论文

        Args:
            query: 搜索关键词
            max_results: 最大结果数

        Returns:
            list[PaperCreate]: 论文列表，source 字段统一设置为 "arxiv"
        """
        papers = self._client.fetch_latest(query, max_results)

        # 统一设置 source 字段
        for paper in papers:
            paper.source = "arxiv"
            paper.source_id = paper.arxiv_id

        return papers

    def download_pdf(self, arxiv_id: str) -> str | None:
        """
        从 ArXiv 下载 PDF

        Args:
            arxiv_id: ArXiv ID（如 "2301.12345"）

        Returns:
            str | None: PDF 本地路径，失败返回 None
        """
        try:
            return self._client.download_pdf(arxiv_id)
        except Exception as exc:
            return None

    def supports_incremental(self) -> bool:
        """ArXiv 支持按提交日期增量抓取"""
        return True
