"""
渠道抽象基类 - 统一多渠道接口
为 ArXiv、IEEE 等论文渠道提供统一的抽象层

特性:
- 统一的渠道接口定义
- 支持多渠道扩展
- 便于测试和 mock

@author Color2333
"""

from abc import ABC, abstractmethod
from typing import Optional

from packages.domain.schemas import PaperCreate


class ChannelBase(ABC):
    """
    论文渠道抽象基类

    所有论文渠道（ArXiv、IEEE 等）都必须实现此接口

    使用示例:
    ```python
    class ArxivChannel(ChannelBase):
        @property
        def name(self) -> str:
            return "arxiv"

        def fetch(self, query: str, max_results: int = 20) -> list[PaperCreate]:
            # 实现 ArXiv 搜索逻辑
            pass
    ```
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """
        渠道名称

        Returns:
            str: 渠道标识（如 "arxiv", "ieee"）
        """
        pass

    @abstractmethod
    def fetch(self, query: str, max_results: int = 20) -> list[PaperCreate]:
        """
        搜索论文

        Args:
            query: 搜索关键词
            max_results: 最大结果数（默认 20）

        Returns:
            list[PaperCreate]: 论文元数据列表
        """
        pass

    @abstractmethod
    def download_pdf(self, paper_id: str) -> str | None:
        """
        下载论文 PDF

        Args:
            paper_id: 渠道论文 ID

        Returns:
            str | None: PDF 本地路径，如果不可用返回 None
        """
        pass

    @abstractmethod
    def supports_incremental(self) -> bool:
        """
        是否支持增量抓取

        Returns:
            bool: True 表示支持增量抓取
        """
        pass

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name='{self.name}')"
