"""
Import 冒烟测试 —— 捕获模块拆分/重命名时的悬空导入与循环引用
@author Color2333
"""

from __future__ import annotations


def test_repositories_importable():
    """所有 repository 类可导入（拆分后 __init__ re-export 必须保持）"""
    from packages.storage.repositories import (
        ActionRepository,
        AgentConversationRepository,
        AgentMessageRepository,
        AgentPendingActionRepository,
        AnalysisRepository,
        BaseQuery,
        BatchJobRepository,
        CitationRepository,
        CSFeedRepository,
        DailyReportConfigRepository,
        EmailConfigRepository,
        GeneratedContentRepository,
        IeeeQuotaRepository,
        LLMConfigRepository,
        PaperRepository,
        PipelineRunRepository,
        PromptTraceRepository,
        TagRepository,
        TopicRepository,
    )

    # 全部是类
    for cls in [
        BaseQuery,
        PaperRepository,
        TagRepository,
        AnalysisRepository,
        PipelineRunRepository,
        PromptTraceRepository,
        CitationRepository,
        TopicRepository,
        LLMConfigRepository,
        GeneratedContentRepository,
        ActionRepository,
        EmailConfigRepository,
        AgentConversationRepository,
        AgentMessageRepository,
        DailyReportConfigRepository,
        IeeeQuotaRepository,
        AgentPendingActionRepository,
        CSFeedRepository,
        BatchJobRepository,
    ]:
        assert isinstance(cls, type)


def test_repositories_constructible(db_session):
    """每个 repository 可用测试 session 构造（捕获 __init__ 签名变化）"""
    from packages.storage.repositories import (
        ActionRepository,
        AgentConversationRepository,
        AgentMessageRepository,
        AgentPendingActionRepository,
        AnalysisRepository,
        BatchJobRepository,
        CitationRepository,
        CSFeedRepository,
        DailyReportConfigRepository,
        EmailConfigRepository,
        GeneratedContentRepository,
        IeeeQuotaRepository,
        LLMConfigRepository,
        PaperRepository,
        PipelineRunRepository,
        PromptTraceRepository,
        TagRepository,
        TopicRepository,
    )

    for cls in [
        PaperRepository,
        TagRepository,
        AnalysisRepository,
        PipelineRunRepository,
        PromptTraceRepository,
        CitationRepository,
        TopicRepository,
        LLMConfigRepository,
        GeneratedContentRepository,
        ActionRepository,
        EmailConfigRepository,
        AgentConversationRepository,
        AgentMessageRepository,
        DailyReportConfigRepository,
        IeeeQuotaRepository,
        AgentPendingActionRepository,
        CSFeedRepository,
        BatchJobRepository,
    ]:
        instance = cls(db_session)
        assert instance is not None


def test_ai_modules_importable():
    """关键 AI 模块可导入（捕获 prompts/system_prompt 提取后的导入链）"""
    import packages.ai.agent_service
    import packages.ai.agent_tools
    import packages.ai.graph_service
    import packages.ai.pipelines
    import packages.ai.prompts
    import packages.ai.rag_service

    assert all(
        mod is not None
        for mod in [
            packages.ai.agent_service,
            packages.ai.agent_tools,
            packages.ai.prompts,
            packages.ai.pipelines,
            packages.ai.rag_service,
            packages.ai.graph_service,
        ]
    )


def test_agent_core_importable():
    """agent_core 可导入（捕获 loop/sse 提取后的导入链）"""
    from packages.agent_core.dispatcher import ToolDispatcher
    from packages.agent_core.loop import StreamingAgentLoop

    assert StreamingAgentLoop is not None
    assert ToolDispatcher is not None


def test_integrations_importable():
    """integrations 可导入（捕获 json_repair/pricing 提取后的导入链）"""
    import packages.integrations.llm_client

    assert packages.integrations.llm_client is not None
