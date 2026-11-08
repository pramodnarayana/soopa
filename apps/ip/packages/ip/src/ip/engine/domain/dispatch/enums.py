"""Outbound dispatch and delivery domain enumerations."""

from enum import StrEnum


class OutboundDispatchStatus(StrEnum):
    """Lifecycle status of an external outbound dispatch execution."""

    PENDING = "PENDING"
    IN_FLIGHT = "IN_FLIGHT"
    RATE_LIMITED = "RATE_LIMITED"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"


class HttpWriteOperation(StrEnum):
    """Supported outbound write operations for generic HTTP streams."""

    CREATE = "CREATE"
    UPDATE = "UPDATE"
    UPSERT = "UPSERT"
    DELETE = "DELETE"


class OutboundFailureCategory(StrEnum):
    """First-class semantic failure classification for Layer-5 outbound dispatches."""

    RATE_LIMITED = "RATE_LIMITED"
    AUTH_EXPIRED = "AUTH_EXPIRED"
    TRANSIENT = "TRANSIENT"
    CONFLICT_IDEMPOTENT = "CONFLICT_IDEMPOTENT"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    TERMINAL = "TERMINAL"


class OutboundConflictStrategy(StrEnum):
    """Policy governing how HTTP 409 Conflict responses are handled during outbound writes."""

    FAIL = "FAIL"
    IDEMPOTENT_SUCCESS = "IDEMPOTENT_SUCCESS"


class TokenRefreshPolicy(StrEnum):
    """Strategy governing OAuth2 token evaluation inside TokenManagerService."""

    PROACTIVE_IF_EXPIRING = "PROACTIVE_IF_EXPIRING"
    FORCE_ROTATION = "FORCE_ROTATION"


class BatchFailurePolicy(StrEnum):
    """Strategy governing batch execution behavior when a single item fails terminally."""

    CONTINUE_ALL = "CONTINUE_ALL"
    HALT_ON_TERMINAL = "HALT_ON_TERMINAL"


class FailureDisposition(StrEnum):
    """Actionable engine disposition indicating how upstream workflows should handle this failure."""

    RETRY = "RETRY"
    FAIL = "FAIL"
    IGNORE = "IGNORE"


class TransportType(StrEnum):
    """Transport protocol used to ingest data into Layer 1."""

    HTTP = "HTTP"
    SFTP = "SFTP"
    DATABASE = "DATABASE"
    KAFKA = "KAFKA"
    RABBITMQ = "RABBITMQ"
    MQTT = "MQTT"
    SQS = "SQS"


class AckVerdict(StrEnum):
    """Broker acknowledgment decision dispatched strictly after L1 database commit."""

    ACK = "ACK"
    NACK = "NACK"
    REJECT = "REJECT"
