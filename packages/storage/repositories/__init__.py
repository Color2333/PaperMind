"""
数据仓储层
@author Color2333

拆分为 per-aggregate 子模块后的 re-export 入口；保持
``from packages.storage.repositories import X`` 调用兼容。
"""

from packages.storage.repositories._base import BaseQuery
from packages.storage.repositories.action import ActionRepository
from packages.storage.repositories.agent import (
    AgentConversationRepository,
    AgentMessageRepository,
    AgentPendingActionRepository,
)
from packages.storage.repositories.analysis import AnalysisRepository
from packages.storage.repositories.batch import BatchJobRepository
from packages.storage.repositories.citation import CitationRepository
from packages.storage.repositories.cs_feed import CSFeedRepository
from packages.storage.repositories.daily_report import DailyReportConfigRepository
from packages.storage.repositories.email_config import EmailConfigRepository
from packages.storage.repositories.generated_content import GeneratedContentRepository
from packages.storage.repositories.ieee_quota import IeeeQuotaRepository
from packages.storage.repositories.llm_config import LLMConfigRepository
from packages.storage.repositories.paper import PaperRepository
from packages.storage.repositories.pipeline import PipelineRunRepository
from packages.storage.repositories.prompt_trace import PromptTraceRepository
from packages.storage.repositories.tag import TagRepository
from packages.storage.repositories.topic import TopicRepository

__all__ = [
    "BaseQuery",
    "PaperRepository",
    "TagRepository",
    "AnalysisRepository",
    "PipelineRunRepository",
    "PromptTraceRepository",
    "CitationRepository",
    "TopicRepository",
    "LLMConfigRepository",
    "GeneratedContentRepository",
    "ActionRepository",
    "EmailConfigRepository",
    "AgentConversationRepository",
    "AgentMessageRepository",
    "DailyReportConfigRepository",
    "IeeeQuotaRepository",
    "AgentPendingActionRepository",
    "CSFeedRepository",
    "BatchJobRepository",
]
