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
