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
from packages.integrations.arxiv_channel import ArxivChannel

# 原始客户端
from packages.integrations.arxiv_client import ArxivClient
from packages.integrations.biorxiv_channel import BiorxivChannel
from packages.integrations.biorxiv_client import BiorxivClient
from packages.integrations.channel_base import ChannelBase
from packages.integrations.dblp_channel import DblpChannel
from packages.integrations.dblp_client import DblpClient
from packages.integrations.ieee_channel import IeeeChannel
from packages.integrations.ieee_client import IeeeClient, create_ieee_client
from packages.integrations.llm_client import LLMClient
from packages.integrations.openalex_client import OpenAlexClient
from packages.integrations.openalex_search_channel import OpenAlexSearchChannel
from packages.integrations.openalex_search_client import OpenAlexSearchClient

# 注册表
from packages.integrations.registry import ChannelRegistry, register_channel
from packages.integrations.semantic_scholar_client import SemanticScholarClient
from packages.integrations.semantic_scholar_search_channel import SemanticScholarSearchChannel
from packages.integrations.semantic_scholar_search_client import SemanticScholarSearchClient

__all__ = [
    # 渠道适配器
    "ChannelBase",
    "ArxivChannel",
    "IeeeChannel",
    "OpenAlexSearchChannel",
    "SemanticScholarSearchChannel",
    "DblpChannel",
    "BiorxivChannel",
    # 注册表
    "ChannelRegistry",
    "register_channel",
    # 原始客户端
    "ArxivClient",
    "IeeeClient",
    "create_ieee_client",
    "SemanticScholarClient",
    "SemanticScholarSearchClient",
    "OpenAlexClient",
    "OpenAlexSearchClient",
    "DblpClient",
    "BiorxivClient",
    "LLMClient",
]
