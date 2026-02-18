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
