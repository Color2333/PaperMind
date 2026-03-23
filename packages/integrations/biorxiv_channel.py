"""
bioRxiv 渠道适配器
将 BiorxivClient 适配到 ChannelBase 接口

@author Color2333
"""

from packages.domain.schemas import PaperCreate
from packages.integrations.biorxiv_client import BiorxivClient
from packages.integrations.channel_base import ChannelBase


class BiorxivChannel(ChannelBase):
    """
    bioRxiv/medRxiv 预印本渠道适配器

    特性:
    - 预印本论文搜索（生物学/医学）
    - 支持 bioRxiv 和 medRxiv 两个服务器
    - 不支持 PDF 下载
    - 支持增量抓取

    使用示例:
    ```python
    channel = BiorxivChannel()
    papers = channel.fetch("CRISPR", max_results=20)
    ```
    """

    def __init__(self, server: str = "biorxiv") -> None:
        self.server = server
        self._client = BiorxivClient()

    @property
    def name(self) -> str:
        return self.server

    def fetch(self, query: str, max_results: int = 20) -> list[PaperCreate]:
        """从 bioRxiv/medRxiv 搜索预印本"""
        return self._client.search_papers(query, max_results, server=self.server)

    def download_pdf(self, paper_id: str) -> str | None:
        """预印本 PDF 需要到对应网站下载，返回 None"""
        return None

    def supports_incremental(self) -> bool:
        """预印本支持按日期增量抓取"""
        return True
