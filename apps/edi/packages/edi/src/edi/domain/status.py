from enum import StrEnum


class MessageStatus(StrEnum):
    RECEIVED = "RECEIVED"
    ACCEPTED = "ACCEPTED"
    PARSED = "PARSED"
    TRANSFORMED = "TRANSFORMED"
    PENDING_DELIVERY = "PENDING_DELIVERY"
    PROCESSING = "PROCESSING"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    ERROR = "ERROR"


class AuditLogStatus(StrEnum):
    """Status values for the AuditLog step-level tracing model."""

    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    SKIPPED = "SKIPPED"
