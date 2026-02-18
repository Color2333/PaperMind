"""
SQLAlchemy ORM 模型定义
@author Bamzc
"""
from datetime import UTC, date, datetime
from uuid import uuid4

from sqlalchemy import (
    Integer,
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
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

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    title: Mapped[str] = mapped_column(String(1024), nullable=False)
    arxiv_id: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    abstract: Mapped[str] = mapped_column(Text, nullable=False, default="")
    pdf_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    publication_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    read_status: Mapped[ReadStatus] = mapped_column(
        Enum(ReadStatus, name="read_status"),
        nullable=False,
        default=ReadStatus.unread,
    )
    metadata_json: Mapped[dict] = mapped_column(
        "metadata", JSON, nullable=False, default=dict
    )
    favorited: Mapped[bool] = mapped_column(
        nullable=False, default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )


class AnalysisReport(Base):
    __tablename__ = "analysis_reports"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    paper_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("papers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    summary_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    deep_dive_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_insights: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict
    )
    skim_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )


class ImageAnalysis(Base):
    """论文图表/公式解读结果"""

    __tablename__ = "image_analyses"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    paper_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("papers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    page_number: Mapped[int] = mapped_column(nullable=False)
    image_index: Mapped[int] = mapped_column(nullable=False, default=0)
    image_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="figure"
    )
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    bbox_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False
    )


class Citation(Base):
    __tablename__ = "citations"
    __table_args__ = (
        UniqueConstraint(
            "source_paper_id", "target_paper_id", name="uq_citation_edge"
        ),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
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

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    paper_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("papers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    pipeline_name: Mapped[str] = mapped_column(
        String(100), nullable=False, index=True
    )
    status: Mapped[PipelineStatus] = mapped_column(
        Enum(PipelineStatus, name="pipeline_status"),
        nullable=False,
        default=PipelineStatus.pending,
    )
    retry_count: Mapped[int] = mapped_column(nullable=False, default=0)
    elapsed_ms: Mapped[int | None] = mapped_column(nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )


class PromptTrace(Base):
    __tablename__ = "prompt_traces"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False
    )


class SourceCheckpoint(Base):
    __tablename__ = "source_checkpoints"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    source: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True
    )
    last_fetch_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    last_published_date: Mapped[date | None] = mapped_column(
        Date, nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )


class TopicSubscription(Base):
    __tablename__ = "topic_subscriptions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    name: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True
    )
    query: Mapped[str] = mapped_column(String(1024), nullable=False)
    enabled: Mapped[bool] = mapped_column(nullable=False, default=True)
    max_results_per_run: Mapped[int] = mapped_column(
        nullable=False, default=20
    )
    retry_limit: Mapped[int] = mapped_column(nullable=False, default=2)
    schedule_frequency: Mapped[str] = mapped_column(
        String(20), nullable=False, default="daily"
    )
    schedule_time_utc: Mapped[int] = mapped_column(
        nullable=False, default=21
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )


class PaperTopic(Base):
    __tablename__ = "paper_topics"
    __table_args__ = (
        UniqueConstraint("paper_id", "topic_id", name="uq_paper_topic"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False
    )


class LLMProviderConfig(Base):
    """用户可配置的 LLM 提供者"""

    __tablename__ = "llm_provider_configs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    name: Mapped[str] = mapped_column(
        String(128), nullable=False, unique=True
    )
    provider: Mapped[str] = mapped_column(
        String(32), nullable=False
    )
    api_key: Mapped[str] = mapped_column(
        String(512), nullable=False
    )
    api_base_url: Mapped[str | None] = mapped_column(
        String(512), nullable=True
    )
    model_skim: Mapped[str] = mapped_column(
        String(128), nullable=False
    )
    model_deep: Mapped[str] = mapped_column(
        String(128), nullable=False
    )
    model_vision: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )
    model_embedding: Mapped[str] = mapped_column(
        String(128), nullable=False
    )
    model_fallback: Mapped[str] = mapped_column(
        String(128), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow, nullable=False
    )


class GeneratedContent(Base):
    """持久化存储的生成内容（Wiki / 简报等）"""

    __tablename__ = "generated_contents"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
    content_type: Mapped[str] = mapped_column(
        String(32), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(
        String(512), nullable=False
    )
    keyword: Mapped[str | None] = mapped_column(
        String(256), nullable=True
    )
    paper_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("papers.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    markdown: Mapped[str] = mapped_column(
        Text, nullable=False, default=""
    )
    metadata_json: Mapped[dict] = mapped_column(
        JSON, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False
    )


class CollectionAction(Base):
    """论文入库行动记录"""

    __tablename__ = "collection_actions"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
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
    paper_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, nullable=False
    )


class ActionPaper(Base):
    """行动-论文关联表"""

    __tablename__ = "action_papers"
    __table_args__ = (
        UniqueConstraint("action_id", "paper_id", name="uq_action_paper"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid4())
    )
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
