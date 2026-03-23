"""
DBLP 渠道适配器
将 DblpClient 适配到 ChannelBase 接口

@author Color2333
"""

from packages.domain.schemas import PaperCreate
from packages.integrations.channel_base import ChannelBase
from packages.integrations.dblp_client import DblpClient


class DblpChannel(ChannelBase):
    """
    DBLP 渠道适配器

    特性:
    - CS 会议/期刊论文搜索（NeurIPS, ICML, CVPR 等）
    - 使用 CrossRef API 作为后端
    - 不支持 PDF 下载
    - 支持增量抓取（按年份）

    使用示例:
    ```python
    channel = DblpChannel()
    papers = channel.fetch("neural network", max_results=20)
    ```
    """

    def __init__(self, email: str | None = None) -> None:
        self._client = DblpClient(email=email)

    @property
    def name(self) -> str:
        return "dblp"

    def fetch(self, query: str, max_results: int = 20) -> list[PaperCreate]:
        """从 DBLP 搜索 CS 论文"""
        return self._client.search_papers(query, max_results)

    def download_pdf(self, paper_id: str) -> str | None:
        """DBLP 不提供 PDF 下载，返回 None"""
        return None

    def supports_incremental(self) -> bool:
        """DBLP 支持按年份增量抓取"""
        return True
