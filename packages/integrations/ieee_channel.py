"""
IEEE 渠道适配器
将 IEEE 客户端适配到 ChannelBase 接口

@author Color2333
"""

import os
from packages.config import get_settings
from packages.integrations.ieee_client import IeeeClient
from packages.integrations.channel_base import ChannelBase
from packages.domain.schemas import PaperCreate


class IeeeChannel(ChannelBase):
    """
    IEEE 渠道适配器
    
    特性:
    - 复用 IeeeClient
    - IEEE PDF 下载受限（返回 None）
    - 不支持可靠的增量抓取
    
    使用示例:
    ```python
    channel = IeeeChannel(api_key="xxx")
    papers = channel.fetch("machine learning", max_results=20)
    ```
    """
    
    def __init__(self, api_key: str | None = None) -> None:
        """
        初始化 IEEE 渠道
        
        Args:
            api_key: IEEE API Key（可选，默认从环境变量读取）
        """
        settings = get_settings()
        # 优先使用传入的 api_key，其次从环境变量读取
        self.api_key = api_key or os.getenv("IEEE_API_KEY")
        self._client = IeeeClient(api_key=self.api_key)
    
    @property
    def name(self) -> str:
        return "ieee"
    
    def fetch(self, query: str, max_results: int = 20) -> list[PaperCreate]:
        """
        从 IEEE 搜索论文
        
        Args:
            query: 搜索关键词
            max_results: 最大结果数
        
        Returns:
            list[PaperCreate]: 论文列表，source 字段统一设置为 "ieee"
        """
        if not self.api_key:
            return []
        
        return self._client.fetch_by_keywords(query, max_results)
    
    def download_pdf(self, ieee_doc_id: str) -> str | None:
        """
        IEEE PDF 下载（暂不支持）
        
        ⚠️ 注意：IEEE PDF 需要机构订阅，目前返回 None
        
        Args:
            ieee_doc_id: IEEE Document ID
        
        Returns:
            None: IEEE PDF 暂不可用
        """
        # IEEE PDF 下载需要额外的认证流程
        # 目前返回 None，上层逻辑应处理此情况
        return None
    
    def supports_incremental(self) -> bool:
        """IEEE 不支持可靠的增量抓取"""
        return False
