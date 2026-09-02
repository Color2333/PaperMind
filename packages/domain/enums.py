from enum import StrEnum


class ReadStatus(StrEnum):
    unread = "unread"
    skimmed = "skimmed"
    deep_read = "deep_read"


class PipelineStatus(StrEnum):
    pending = "pending"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class ActionType(StrEnum):
    """论文入库行动类型"""

    initial_import = "initial_import"
    manual_collect = "manual_collect"
    auto_collect = "auto_collect"
    agent_collect = "agent_collect"
    subscription_ingest = "subscription_ingest"
    reference_import = "reference_import"


# ---------- Research State（设计①数据契约）----------
# 注意：SQLAlchemy Enum 默认按成员 name 落库；EventType 的 name 为 snake_case、
# value 为设计文档事件词汇表（PascalCase），对外序列化输出 value。


class QuestionStatus(StrEnum):
    active = "active"
    archived = "archived"


class SourceDetectedBy(StrEnum):
    ingest = "ingest"
    watch = "watch"
    manual = "manual"


class ClaimOrigin(StrEnum):
    """判断来源三分：作者声称 / PaperMind 推断 / 用户判断"""

    author = "author"
    papermind = "papermind"
    user = "user"


class ClaimStatus(StrEnum):
    draft = "draft"
    pending_verification = "pending_verification"
    confirmed = "confirmed"
    superseded = "superseded"
    invalidated = "invalidated"


class ClaimCertainty(StrEnum):
    """不确定性枚举（不是分数）：established 与 status 正交"""

    established = "established"
    conditional = "conditional"
    conflicted = "conflicted"
    insufficient_evidence = "insufficient_evidence"
    unknown = "unknown"


class EvidenceKind(StrEnum):
    text_passage = "text_passage"
    figure = "figure"
    table = "table"
    formula = "formula"
    numeric_result = "numeric_result"
    dataset = "dataset"


class EvidenceStance(StrEnum):
    """证据相对 Claim 的方向"""

    supports = "supports"
    contradicts = "contradicts"
    context = "context"


class RelationPredicate(StrEnum):
    """关系谓词全集；P0 工作流只产生 supports/contradicts/supersedes，其余预留"""

    supports = "supports"
    partially_supports = "partially_supports"
    contradicts = "contradicts"
    conditional = "conditional"
    replication_failed = "replication_failed"
    supersedes = "supersedes"


class RelationOrigin(StrEnum):
    papermind = "papermind"
    user = "user"


class RunTrigger(StrEnum):
    manual = "manual"
    watch = "watch"
    scheduler = "scheduler"
    api = "api"


class ResearchRunStatus(StrEnum):
    running = "running"
    succeeded = "succeeded"
    failed = "failed"
    partial = "partial"


class EventAggregate(StrEnum):
    source = "source"
    source_version = "source_version"
    claim = "claim"
    evidence = "evidence"
    relation = "relation"
    run = "run"


class EventType(StrEnum):
    """设计文档 §4.7 事件清单 + ClaimRelationRecorded（冲突/取代 diff 需要）"""

    source_added = "SourceAdded"
    source_version_detected = "SourceVersionDetected"
    evidence_extracted = "EvidenceExtracted"
    claim_proposed = "ClaimProposed"
    claim_confirmed = "ClaimConfirmed"
    claim_revised = "ClaimRevised"
    claim_invalidated = "ClaimInvalidated"
    claim_relation_recorded = "ClaimRelationRecorded"
    retraction_detected = "RetractionDetected"
    research_run_completed = "ResearchRunCompleted"
    job_failed = "JobFailed"
