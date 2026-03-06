"""
集成模块包
提供外部 API 客户端和渠道适配器

渠道适配器（完整版新增）:
- ChannelBase: 渠道抽象基类
- ArxivChannel: ArXiv 渠道适配器
- IeeeChannel: IEEE 渠道适配器

原始客户端:
- ArxivClient, IeeeClient, SemanticScholarClient, OpenAlexClient, LLMClient
"""

# 渠道适配器（完整版新增）
from packages.integrations.channel_base import ChannelBase
from packages.integrations.arxiv_channel import ArxivChannel
from packages.integrations.ieee_channel import IeeeChannel

# 原始客户端
from packages.integrations.arxiv_client import ArxivClient
from packages.integrations.ieee_client import IeeeClient, create_ieee_client
from packages.integrations.semantic_scholar_client import SemanticScholarClient
from packages.integrations.openalex_client import OpenAlexClient
from packages.integrations.llm_client import LLMClient

__all__ = [
    # 渠道适配器
    "ChannelBase",
    "ArxivChannel",
    "IeeeChannel",
    # 原始客户端
    "ArxivClient",
    "IeeeClient",
    "create_ieee_client",
    "SemanticScholarClient",
    "OpenAlexClient",
    "LLMClient",
]