"""
SQLAlchemy ORM 模型定义
@author Color2333
"""

from datetime import UTC, date, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from packages.domain.enums import ActionType, PipelineStatus, ReadStatus
from packages.storage.db import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Paper(Base):
    __tablename__ = "papers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    arxiv_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    abstract: Mapped[str] = mapped_column(Text, nullable=False, default="")
    pdf_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    publication_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    read_status: Mapped[ReadStatus] = mapped_column(
        Enum(ReadStatus, name="read_status"),
        nullable=False,
        default=ReadStatus.unread,
        index=True,
    )
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)
    favorited: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )

    __table_args__ = (Index("ix_papers_read_status_created_at", "read_status", "created_at"),)


class AnalysisReport(Base):
    __tablename__ = "analysis_reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    paper_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("papers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    summary_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    deep_dive_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_insights: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    skim_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )


class ImageAnalysis(Base):
    """论文图表/公式解读结果"""

    __tablename__ = "image_analyses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    paper_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("papers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    page_number: Mapped[int] = mapped_column(nullable=False)
    image_index: Mapped[int] = mapped_column(nullable=False, default=0)
    image_type: Mapped[str] = mapped_column(String(32), nullable=False, default="figure")
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    image_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    bbox_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


class Citation(Base):
    __tablename__ = "citations"
    __table_args__ = (
        UniqueConstraint("source_paper_id", "target_paper_id", name="uq_citation_edge"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    source_paper_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("papers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_paper_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("papers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    context: Mapped[str | None] = mapped_column(Text, nullable=True)


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    paper_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("papers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    pipeline_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[PipelineStatus] = mapped_column(
        Enum(PipelineStatus, name="pipeline_status"),
        nullable=False,
        default=PipelineStatus.pending,
    )
    retry_count: Mapped[int] = mapped_column(nullable=False, default=0)
    elapsed_ms: Mapped[int | None] = mapped_column(nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )


class PromptTrace(Base):
    __tablename__ = "prompt_traces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    paper_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("papers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    stage: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_digest: Mapped[str] = mapped_column(Text, nullable=False)
    input_tokens: Mapped[int | None] = mapped_column(nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(nullable=True)
    input_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    output_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


class SourceCheckpoint(Base):
    __tablename__ = "source_checkpoints"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    source: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    last_fetch_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_published_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )


class TopicSubscription(Base):
    __tablename__ = "topic_subscriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    query: Mapped[str] = mapped_column(String(1024), nullable=False)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    max_results_per_run: Mapped[int] = mapped_column(nullable=False, default=20)
    retry_limit: Mapped[int] = mapped_column(nullable=False, default=2)
    schedule_frequency: Mapped[str] = mapped_column(String(32), nullable=False, default="daily")
    schedule_time_utc: Mapped[int] = mapped_column(nullable=False, default=21)
    enable_date_filter: Mapped[bool] = mapped_column(
        nullable=False, default=False
    )  # 是否启用日期过滤
    date_filter_days: Mapped[int] = mapped_column(
        nullable=False, default=7
    )  # 日期范围（最近 N 天）
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )


class PaperTopic(Base):
    __tablename__ = "paper_topics"
    __table_args__ = (UniqueConstraint("paper_id", "topic_id", name="uq_paper_topic"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    paper_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("papers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    topic_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("topic_subscriptions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


class LLMProviderConfig(Base):
    """用户可配置的 LLM 提供者"""

    __tablename__ = "llm_provider_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    api_key: Mapped[str] = mapped_column(String(512), nullable=False)
    api_base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    model_skim: Mapped[str] = mapped_column(String(128), nullable=False)
    model_deep: Mapped[str] = mapped_column(String(128), nullable=False)
    model_vision: Mapped[str | None] = mapped_column(String(128), nullable=True)
    model_embedding: Mapped[str] = mapped_column(String(128), nullable=False)
    model_fallback: Mapped[str] = mapped_column(String(128), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )


class GeneratedContent(Base):
    """生成的内容（Wiki/报告/简报等）"""

    __tablename__ = "generated_contents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    content_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    keyword: Mapped[str | None] = mapped_column(String(256), nullable=True)
    paper_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("papers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    markdown: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False, index=True
    )


# ========== Agent 对话相关 ==========


class AgentConversation(Base):
    """Agent 对话会话"""

    __tablename__ = "agent_conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )


class AgentMessage(Base):
    """Agent 对话消息"""

    __tablename__ = "agent_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    conversation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("agent_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,  # user/assistant/system
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False, index=True
    )


class AgentPendingAction(Base):
    """Agent 待确认操作 - 持久化存储"""

    __tablename__ = "agent_pending_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("agent_conversations.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    tool_args: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    tool_call_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    conversation_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False, index=True
    )

    paper_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("papers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    markdown: Mapped[str] = mapped_column(Text, nullable=False, default="")
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


class CollectionAction(Base):
    """论文入库行动记录"""

    __tablename__ = "collection_actions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    action_type: Mapped[ActionType] = mapped_column(
        Enum(ActionType, name="action_type"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    query: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    topic_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("topic_subscriptions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    paper_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


class ActionPaper(Base):
    """行动-论文关联表"""

    __tablename__ = "action_papers"
    __table_args__ = (UniqueConstraint("action_id", "paper_id", name="uq_action_paper"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    action_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("collection_actions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    paper_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("papers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )


class EmailConfig(Base):
    """邮箱配置 - 用于发送每日简报"""

    __tablename__ = "email_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    smtp_server: Mapped[str] = mapped_column(String(256), nullable=False)
    smtp_port: Mapped[int] = mapped_column(Integer, nullable=False, default=587)
    smtp_use_tls: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sender_email: Mapped[str] = mapped_column(String(256), nullable=False)
    sender_name: Mapped[str] = mapped_column(String(128), nullable=False, default="PaperMind")
    username: Mapped[str] = mapped_column(String(256), nullable=False)
    password: Mapped[str] = mapped_column(String(512), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )


class DailyReportConfig(Base):
    """每日报告配置 - 自动精读和邮件发送设置"""

    __tablename__ = "daily_report_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    auto_deep_read: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, doc="是否自动精读新搜集的论文"
    )
    deep_read_limit: Mapped[int] = mapped_column(
        Integer, nullable=False, default=10, doc="每日自动精读的论文数量限制"
    )
    send_email_report: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, doc="是否发送邮件报告"
    )
    recipient_emails: Mapped[str] = mapped_column(
        String(2048), nullable=False, default="", doc="收件人邮箱列表，逗号分隔"
    )
    cron_expression: Mapped[str] = mapped_column(
        String(64), nullable=False, default="0 4 * * *", doc="定时任务 cron 表达式（UTC 时间）"
    )
    report_time_utc: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=21,
        doc="发送报告的时间（UTC，0-23）- 已废弃，使用 cron_expression",
    )
    include_paper_details: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, doc="报告中是否包含论文详情"
    )
    include_graph_insights: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, doc="报告中是否包含图谱洞察"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )


class CSCategory(Base):
    """arXiv 计算机科学分类"""

    __tablename__ = "cs_categories"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)  # "cs.CV"
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(String(512), default="")
    cached_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class CSFeedSubscription(Base):
    """arXiv CS 分类订阅"""

    __tablename__ = "cs_feed_subscriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    category_code: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    daily_limit: Mapped[int] = mapped_column(Integer, default=30)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(32), default="active")  # active | cool_down | paused
    cool_down_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_run_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
