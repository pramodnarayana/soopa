"""Transaction Domain Enumerations."""

from enum import StrEnum


class MessageStatus(StrEnum):
    """Lifecycle status of an EDI message or JSON record."""

    RECEIVED = "RECEIVED"
    ACCEPTED = "ACCEPTED"
    PENDING = "PENDING"
    PARSED = "PARSED"
    TRANSFORMED = "TRANSFORMED"
    PENDING_DELIVERY = "PENDING_DELIVERY"
    DELIVERED = "DELIVERED"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    ERROR = "ERROR"


RecordStatus = MessageStatus


class AuditLogStatus(StrEnum):
    """Status values for the AuditLog step-level tracing model."""

    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    SKIPPED = "SKIPPED"


class EdiStandard(StrEnum):
    """The EDI format standard of the message payload."""

    X12 = "x12"
    EDIFACT = "edifact"


class EdiTransactionType(StrEnum):
    """Well-known X12 transaction set identifiers plus the generic envelope type."""

    ENVELOPE = "envelope"
    X12_204 = "204"
    X12_210 = "210"
    X12_214 = "214"
    X12_810 = "810"
    X12_850 = "850"
    X12_990 = "990"
    X12_997 = "997"


class PipelineEventType(StrEnum):
    """Internal pipeline orchestration event types (SQS message type discriminators)."""

    TRANSFORMATION_REQUESTED = "TRANSFORMATION_REQUESTED"
    COMPUTE_TRANSFORMATION_COMMAND = "COMPUTE_TRANSFORMATION_COMMAND"
    TRANSFORMATION_SUCCESSFUL = "TRANSFORMATION_SUCCESSFUL"
    TRANSFORMATION_FAILED = "TRANSFORMATION_FAILED"
    DELIVERY_REQUESTED = "DELIVERY_REQUESTED"
    EXECUTE_DELIVERY_COMMAND = "EXECUTE_DELIVERY_COMMAND"
    DELIVERY_COMPLETED = "DELIVERY_COMPLETED"
    DELIVERY_SUCCESSFUL = "DELIVERY_SUCCESSFUL"
    DELIVERY_FAILED = "DELIVERY_FAILED"


class NotificationEventType(StrEnum):
    """Cross-bounded-context notification trigger event type."""

    NOTIFICATION_TRIGGERED = "notification.triggered"


class ReplayCheckpoint(StrEnum):
    """The pipeline stage from which to resume processing during a replay.

    TRANSFORM — restart from the raw EDI payload (re-run transform + deliver).
    DELIVERY  — restart from the translated JSON (re-run deliver only, skip transform).
    """

    TRANSFORM = "TRANSFORM"
    DELIVERY = "DELIVERY"
