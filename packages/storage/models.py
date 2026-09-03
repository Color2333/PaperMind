"""
SQLAlchemy ORM 模型定义
@author Color2333
"""

from datetime import UTC, date, datetime
from uuid import uuid4

from sqlalchemy import (
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

from packages.domain.enums import (
    ActionType,
    ClaimCertainty,
    ClaimOrigin,
    ClaimStatus,
    EventAggregate,
    EventType,
    EvidenceKind,
    EvidenceStance,
    JobStatus,
    PipelineStatus,
    QuestionStatus,
    ReadStatus,
    RelationOrigin,
    RelationPredicate,
    ResearchRunStatus,
    RunTrigger,
    SourceDetectedBy,
    TaskAttemptStatus,
    TaskStatus,
)
from packages.domain.ids import new_id
from packages.storage.db import Base, JSONB_or_JSON, Vector_or_JSON


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Paper(Base):
    __tablename__ = "papers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    arxiv_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    abstract: Mapped[str] = mapped_column(Text, nullable=False, default="")
    pdf_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    publication_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    embedding: Mapped[list[float] | None] = mapped_column(
        "embedding_vec", Vector_or_JSON(1024), nullable=True
    )
    read_status: Mapped[ReadStatus] = mapped_column(
        Enum(ReadStatus, name="read_status"),
        nullable=False,
        default=ReadStatus.unread,
        index=True,
    )
    metadata_json: Mapped[dict] = mapped_column(
        "metadata", JSONB_or_JSON(), nullable=False, default=dict
    )
    favorited: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
        index=True,
    )
    # 负反馈标记：用户标记"不感兴趣"的论文，推荐/候选查询统一排除。
    # 本轮只预留字段 + 查询排除，UI 后续再加。
    rejected: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
        index=True,
    )
    # 多渠道字段（IEEE / DOI 等非 arXiv 来源）
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="arxiv", index=True)
    source_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    doi: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
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
        unique=True,
    )
    summary_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    deep_dive_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_insights: Mapped[dict] = mapped_column(JSONB_or_JSON(), nullable=False, default=dict)
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
    bbox_json: Mapped[dict | None] = mapped_column(JSONB_or_JSON(), nullable=True)
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
    """主题订阅配置 - 支持多渠道"""

    __tablename__ = "topic_subscriptions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    query: Mapped[str] = mapped_column(String(1024), nullable=False)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    max_results_per_run: Mapped[int] = mapped_column(nullable=False, default=20)
    retry_limit: Mapped[int] = mapped_column(nullable=False, default=2)
    schedule_frequency: Mapped[str] = mapped_column(String(32), nullable=False, default="daily")
    schedule_time_utc: Mapped[int] = mapped_column(nullable=False, default=21)

    # 完整版新增：多渠道支持
    sources: Mapped[list[str]] = mapped_column(
        JSONB_or_JSON(), nullable=False, default=lambda: ["arxiv"]
    )  # ["arxiv", "ieee"]

    # IEEE 特定配置
    ieee_daily_quota: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=10,  # IEEE 每日 API 调用限额
    )
    ieee_api_key_override: Mapped[str | None] = mapped_column(
        String(512),
        nullable=True,  # 可选的 IEEE API Key 覆盖
    )

    # 日期过滤配置
    enable_date_filter: Mapped[bool] = mapped_column(
        nullable=False, default=False
    )  # 是否启用日期过滤
    date_filter_days: Mapped[int] = mapped_column(
        nullable=False, default=7
    )  # 日期范围（最近 N 天）

    # 抓取状态追踪（修 Critical #4：此前无 last_run_at，抓取失败静默无痕无法补抓）
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)

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
    metadata_json: Mapped[dict | None] = mapped_column(JSONB_or_JSON(), nullable=True)
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
    meta: Mapped[dict | None] = mapped_column(JSONB_or_JSON(), nullable=True)
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
    tool_args: Mapped[dict] = mapped_column(JSONB_or_JSON(), nullable=False, default=dict)
    tool_call_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    conversation_state: Mapped[dict | None] = mapped_column(JSONB_or_JSON(), nullable=True)
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
    metadata_json: Mapped[dict] = mapped_column(JSONB_or_JSON(), nullable=False, default=dict)


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
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False, index=True
    )


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


class IeeeApiQuota(Base):
    """IEEE API 配额追踪"""

    __tablename__ = "ieee_api_quotas"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    topic_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("topic_subscriptions.id"), nullable=True, index=True
    )
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    api_calls_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    api_calls_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    last_reset_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    __table_args__ = (UniqueConstraint("topic_id", "date", name="uq_ieee_quota_daily"),)


class CSCategory(Base):
    """arXiv 计算机科学分类"""

    __tablename__ = "cs_categories"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)  # "cs.CV"
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(String(512), default="")
    cached_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class Tag(Base):
    """用户自定义标签"""

    __tablename__ = "tags"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    color: Mapped[str] = mapped_column(String(32), nullable=False, default="#3b82f6")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )


class PaperTag(Base):
    """论文-标签关联表"""

    __tablename__ = "paper_tags"
    __table_args__ = (UniqueConstraint("paper_id", "tag_id", name="uq_paper_tag"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    paper_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("papers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tag_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("tags.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


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


# ========== Sensemaking 认知重构相关 ==========


class UserSchema(Base):
    __tablename__ = "user_schemas"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)

    research_topics: Mapped[list[str]] = mapped_column(JSONB_or_JSON(), default=list)
    academic_level: Mapped[str | None] = mapped_column(String(64), nullable=True)
    current_challenges: Mapped[list[str]] = mapped_column(JSONB_or_JSON(), default=list)
    beliefs: Mapped[list[str]] = mapped_column(JSONB_or_JSON(), default=list)
    knowledge_gaps: Mapped[list[str]] = mapped_column(JSONB_or_JSON(), default=list)

    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )


class SensemakingSession(Base):
    __tablename__ = "sensemaking_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    paper_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    user_schema_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("user_schemas.id", ondelete="CASCADE"), nullable=False
    )

    act1_comprehension: Mapped[dict | None] = mapped_column(JSONB_or_JSON(), nullable=True)
    act2_collision: Mapped[dict | None] = mapped_column(JSONB_or_JSON(), nullable=True)
    act3_reconstruction: Mapped[dict | None] = mapped_column(JSONB_or_JSON(), nullable=True)

    status: Mapped[str] = mapped_column(String(32), default="in_progress")
    conversation_history: Mapped[list[dict]] = mapped_column(JSONB_or_JSON(), default=list)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SchemaPaperInteraction(Base):
    __tablename__ = "schema_paper_interactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_schema_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("user_schemas.id", ondelete="CASCADE"), nullable=False, index=True
    )
    paper_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)

    interaction_type: Mapped[str] = mapped_column(String(64), nullable=False)
    cognitive_delta: Mapped[dict | None] = mapped_column(JSONB_or_JSON(), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


class PaperTranslation(Base):
    """论文翻译缓存（快速模式分段译文 / 布局保留模式双语 PDF 路径）"""

    __tablename__ = "paper_translations"
    __table_args__ = (
        UniqueConstraint("paper_id", "target_lang", "mode", name="uq_paper_translation"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    paper_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("papers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_lang: Mapped[str] = mapped_column(String(16), nullable=False, default="zh")
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="fast")
    segments: Mapped[list | None] = mapped_column(JSONB_or_JSON(), nullable=True)
    bilingual_pdf_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )


class BatchJob(Base):
    __tablename__ = "batch_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    paper_ids: Mapped[list] = mapped_column(JSONB_or_JSON(), nullable=False, default=list)
    error_log: Mapped[dict] = mapped_column(JSONB_or_JSON(), nullable=False, default=dict)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# ========== 认证：API 令牌 / 设备码授权 ==========


class ApiToken(Base):
    """API 令牌（CLI / MCP / 外部 harness 用）。DB 只存 SHA-256 哈希，明文仅创建时返回一次。"""

    __tablename__ = "api_tokens"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    token_prefix: Mapped[str] = mapped_column(String(16), nullable=False)  # 列表展示用
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    scopes: Mapped[list] = mapped_column(
        JSONB_or_JSON(), nullable=False, default=lambda: ["read", "write"]
    )
    created_by: Mapped[str] = mapped_column(String(16), nullable=False, default="web")  # web|device
    device_request_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def is_active(self) -> bool:
        """是否可用（未吊销且未过期）。读回的 datetime 为 naive UTC，统一归一化后比较。"""
        now = _utcnow().replace(tzinfo=None)
        if self.revoked_at is not None:
            return False
        return not (self.expires_at is not None and self.expires_at.replace(tzinfo=None) < now)


class DeviceAuthRequest(Base):
    """设备码授权请求（CLI pm login 流程），状态机 pending → approved/denied/expired"""

    __tablename__ = "device_auth_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    device_code_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    user_code: Mapped[str] = mapped_column(String(9), nullable=False, unique=True, index=True)
    client_name: Mapped[str] = mapped_column(String(128), nullable=False, default="pm-cli")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", index=True)
    api_token_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("api_tokens.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# ---------- Research State（设计①数据契约，docs/plans/2026-09-02-design-1-*.md）----------
# 主键统一 UUIDv7 hex（String(32)），id 即时间序；与既有 String(36) 表通过外键衔接。


class ResearchQuestion(Base):
    """聚合一个问题的当前研究状态"""

    __tablename__ = "research_questions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[QuestionStatus] = mapped_column(
        Enum(QuestionStatus, name="question_status"),
        nullable=False,
        default=QuestionStatus.active,
        index=True,
    )
    watch_terms: Mapped[list] = mapped_column(JSONB_or_JSON(), nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )


class ResearchRun(Base):
    """一次研究活动的输入/模型/成本/产物（Claim/Evidence 的 provenance 锚点）。

    job_ref/attempt_refs 是 Phase 2 durable execution 的弱引用字符串，
    不跨子系统建外键——执行层表归 Stage C 契约管。
    """

    __tablename__ = "research_runs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    research_question_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("research_questions.id", ondelete="SET NULL"), nullable=True
    )
    trigger: Mapped[RunTrigger] = mapped_column(
        Enum(RunTrigger, name="run_trigger"), nullable=False, default=RunTrigger.manual
    )
    paper_ids: Mapped[list] = mapped_column(JSONB_or_JSON(), nullable=False, default=list)
    model_policy: Mapped[dict] = mapped_column(JSONB_or_JSON(), nullable=False, default=dict)
    status: Mapped[ResearchRunStatus] = mapped_column(
        Enum(ResearchRunStatus, name="research_run_status"),
        nullable=False,
        default=ResearchRunStatus.running,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cost_refs: Mapped[list] = mapped_column(JSONB_or_JSON(), nullable=False, default=list)
    artifact_refs: Mapped[dict] = mapped_column(JSONB_or_JSON(), nullable=False, default=dict)
    job_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    attempt_refs: Mapped[list | None] = mapped_column(JSONB_or_JSON(), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class Claim(Base):
    """可比较、可修订的最小研究判断。

    硬规则（设计① §5）：无证据坐标的判断不能 confirmed；papermind 推断最高
    pending_verification，只有用户（或 author 自动规则）能置为 confirmed。
    """

    __tablename__ = "claims"
    __table_args__ = (Index("ix_claims_question_status", "research_question_id", "status"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    research_question_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("research_questions.id", ondelete="SET NULL"), nullable=True
    )
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    statement_zh: Mapped[str | None] = mapped_column(Text, nullable=True)
    origin: Mapped[ClaimOrigin] = mapped_column(
        Enum(ClaimOrigin, name="claim_origin"), nullable=False
    )
    status: Mapped[ClaimStatus] = mapped_column(
        Enum(ClaimStatus, name="claim_status"),
        nullable=False,
        default=ClaimStatus.draft,
        index=True,
    )
    certainty: Mapped[ClaimCertainty] = mapped_column(
        Enum(ClaimCertainty, name="claim_certainty"),
        nullable=False,
        default=ClaimCertainty.insufficient_evidence,
    )
    superseded_by_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("claims.id", ondelete="SET NULL"), nullable=True
    )
    run_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("research_runs.id", ondelete="SET NULL"), nullable=True
    )
    user_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    confirmed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    invalidated_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )


class SourceVersion(Base):
    """论文的具体版本与内容校验值（事实层的"来源"）。papers 表保持不动。"""

    __tablename__ = "source_versions"
    __table_args__ = (
        UniqueConstraint("paper_id", "version_label", name="uq_source_version"),
        Index("ix_source_versions_paper_current", "paper_id", "is_current"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    paper_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("papers.id", ondelete="CASCADE"), nullable=False
    )
    version_label: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    external_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    doi: Mapped[str | None] = mapped_column(String(128), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    file_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    origin_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    detected_by: Mapped[SourceDetectedBy] = mapped_column(
        Enum(SourceDetectedBy, name="source_detected_by"),
        nullable=False,
        default=SourceDetectedBy.ingest,
    )
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


class Evidence(Base):
    """指向精确原文位置的证据（必须挂 SourceVersion）。

    fingerprint = sha256(claim_id + source_version + kind + locator + quote)，
    唯一约束保证同一 Attempt 重放不产生重复证据行（至少一次执行 + 幂等副作用）。
    """

    __tablename__ = "evidence"
    __table_args__ = (
        UniqueConstraint("fingerprint", name="uq_evidence_fingerprint"),
        Index("ix_evidence_source_version", "source_version_id"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    claim_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_version_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("source_versions.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[EvidenceKind] = mapped_column(
        Enum(EvidenceKind, name="evidence_kind"), nullable=False
    )
    stance: Mapped[EvidenceStance] = mapped_column(
        Enum(EvidenceStance, name="evidence_stance"), nullable=False
    )
    locator: Mapped[dict] = mapped_column(JSONB_or_JSON(), nullable=False, default=dict)
    quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    experiment_conditions: Mapped[dict | None] = mapped_column(JSONB_or_JSON(), nullable=True)
    extracted_by: Mapped[ClaimOrigin] = mapped_column(
        Enum(ClaimOrigin, name="evidence_extracted_by"), nullable=False
    )
    run_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("research_runs.id", ondelete="SET NULL"), nullable=True
    )
    image_analysis_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("image_analyses.id", ondelete="SET NULL"), nullable=True
    )
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


class ClaimRelation(Base):
    """Claim 间关系（supports/contradicts/supersedes …），方向：subject 对 object"""

    __tablename__ = "claim_relations"
    __table_args__ = (
        UniqueConstraint(
            "subject_claim_id", "object_claim_id", "predicate", name="uq_claim_relation"
        ),
        Index("ix_claim_relations_object", "object_claim_id"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    subject_claim_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False
    )
    object_claim_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("claims.id", ondelete="CASCADE"), nullable=False
    )
    predicate: Mapped[RelationPredicate] = mapped_column(
        Enum(RelationPredicate, name="claim_relation_predicate"), nullable=False
    )
    origin: Mapped[RelationOrigin] = mapped_column(
        Enum(RelationOrigin, name="claim_relation_origin"), nullable=False
    )
    run_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("research_runs.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


class ResearchEvent(Base):
    """append-only 领域事件：History 与 outbox 合一（设计① §4.7）。

    与聚合变更同一事务写入；processed_at 是 P1 watch/通知的消费标记，P0 恒为 NULL。
    DB 存枚举 name（snake_case），对外序列化用 value（设计文档 PascalCase）。
    """

    __tablename__ = "research_events"
    __table_args__ = (
        Index("ix_research_events_aggregate", "aggregate_type", "aggregate_id", "occurred_at"),
        Index("ix_research_events_type_time", "type", "occurred_at"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    type: Mapped[EventType] = mapped_column(
        Enum(EventType, name="research_event_type"), nullable=False
    )
    aggregate_type: Mapped[EventAggregate] = mapped_column(
        Enum(EventAggregate, name="research_event_aggregate"), nullable=False
    )
    aggregate_id: Mapped[str] = mapped_column(String(32), nullable=False)
    actor: Mapped[str] = mapped_column(String(128), nullable=False, default="system")
    run_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    job_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    attempt_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB_or_JSON(), nullable=False, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False, index=True
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


# ---------- 原子 durable execution（设计③ §1，Stage C2）----------
# jobs/tasks/task_attempts/artifacts；主键 UUIDv7 hex；Job 状态由子 Task 收敛（§2）。


class Job(Base):
    """应用层用户意图/计划流程（设计③ §1.1）"""

    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_kind_status", "kind", "status"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)  # 设计②命令目录名
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status"),
        nullable=False,
        default=JobStatus.submitted,
        index=True,
    )
    payload: Mapped[dict] = mapped_column(JSONB_or_JSON(), nullable=False, default=dict)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    budget: Mapped[dict] = mapped_column(JSONB_or_JSON(), nullable=False, default=dict)
    research_run_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("research_runs.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[str] = mapped_column(String(128), nullable=False, default="system")
    progress: Mapped[dict] = mapped_column(JSONB_or_JSON(), nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class DurableTask(Base):
    """可独立调度/重放的工作原子（设计③ §1.2）"""

    __tablename__ = "tasks"
    __table_args__ = (
        Index("ix_tasks_job_status", "job_id", "status"),
        Index("ix_tasks_status_resource", "status", "resource_class"),
    )

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    capability: Mapped[str] = mapped_column(String(64), nullable=False)
    handler_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    input_schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus, name="task_status"), nullable=False, default=TaskStatus.queued, index=True
    )
    depends_on: Mapped[list] = mapped_column(JSONB_or_JSON(), nullable=False, default=list)
    input_ref: Mapped[dict] = mapped_column(JSONB_or_JSON(), nullable=False, default=dict)
    output_artifact_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("artifacts.id", ondelete="SET NULL", use_alter=True), nullable=True
    )
    idempotency_key: Mapped[str | None] = mapped_column(String(128), unique=True, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    resource_class: Mapped[str] = mapped_column(String(32), nullable=False, default="default")
    timeout_s: Mapped[int] = mapped_column(Integer, nullable=False, default=600)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 过渡期桥接：tracker task_id（C3）；C7 后为 Go Core task id
    external_ref: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )


class TaskAttempt(Base):
    """Executor 对 Task 的一次真实执行（设计③ §1.3；fencing_token 单调递增）"""

    __tablename__ = "task_attempts"
    __table_args__ = (Index("ix_task_attempts_task", "task_id", "attempt_no"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    executor_id: Mapped[str] = mapped_column(String(64), nullable=False)
    fencing_token: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[TaskAttemptStatus] = mapped_column(
        Enum(TaskAttemptStatus, name="task_attempt_status"),
        nullable=False,
        default=TaskAttemptStatus.running,
    )
    error_class: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    log_ref: Mapped[list] = mapped_column(JSONB_or_JSON(), nullable=False, default=list)
    cost_refs: Mapped[list] = mapped_column(JSONB_or_JSON(), nullable=False, default=list)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class TaskArtifact(Base):
    """Task 的可引用产物（设计③ §1.4；大结果进对象存储，此处存引用）"""

    __tablename__ = "artifacts"
    __table_args__ = (Index("ix_artifacts_task", "task_id", "kind"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    # FK 环（tasks.output_artifact_id ↔ artifacts.task_id）：use_alter 允许 create_all/迁移建表
    task_id: Mapped[str] = mapped_column(
        String(32),
        ForeignKey("tasks.id", ondelete="CASCADE", use_alter=True, name="fk_artifacts_task"),
        nullable=False,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    uri: Mapped[str] = mapped_column(String(1024), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB_or_JSON(), nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
