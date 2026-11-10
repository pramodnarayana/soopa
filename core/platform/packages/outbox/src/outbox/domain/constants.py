from enum import StrEnum


class OutboxStatus(StrEnum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    DELIVERING = "DELIVERING"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"
    COMPLETED = "COMPLETED"
    RESERVED = "RESERVED"
    SUCCESS = "SUCCESS"


class LogicalOutboxChannel(StrEnum):
    """Canonical logical replication message prefixes for zero-bloat stream emission."""

    SOOPA_OUTBOX = "soopa.outbox"
