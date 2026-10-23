"""
IP Domain Enumerations
======================

Single source of truth for all business-level enumeration types in the Integration
Platform (IP) bounded context. Every status, authentication type, synchronization mode,
property type, and event category that carries semantic meaning MUST be defined here as a StrEnum.

Rules:
- No raw string literals in application or domain code — always use these enums.
- Do NOT add enums that belong to infrastructure (e.g. SQLAlchemy column choices
  that have no business meaning). Those stay in the adapter layer.
"""

from enum import StrEnum


class IpTraceEventType(StrEnum):
    """Canonical trace event types recorded in the TracedAggregateRoot audit ledger."""

    L1_INGEST_RECEIVED = "L1_INGEST_RECEIVED"
    L1_INGEST_FAILED = "L1_INGEST_FAILED"
    L1_PULL_PAGE_RECEIVED = "L1_PULL_PAGE_RECEIVED"
    L1_PUSH_RECEIVED = "L1_PUSH_RECEIVED"
    L1_PUSH_REJECTED = "L1_PUSH_REJECTED"
    L1_FETCH_COMPLETED = "L1_FETCH_COMPLETED"
    L2_REPLICA_CREATED = "L2_REPLICA_CREATED"
    L2_REPLICA_UPDATED = "L2_REPLICA_UPDATED"
    L2_REPLICA_UNCHANGED = "L2_REPLICA_UNCHANGED"
    L2_REPLICA_TOMBSTONED = "L2_REPLICA_TOMBSTONED"
    L2_EXTRACTION_REJECTED = "L2_EXTRACTION_REJECTED"
    L3_NORMALIZED = "L3_NORMALIZED"
    L3_NORMALIZATION_FAILED = "L3_NORMALIZATION_FAILED"
    L4_DOMAIN_HYDRATED = "L4_DOMAIN_HYDRATED"
    L5_DISPATCH_PENDING = "L5_DISPATCH_PENDING"
    L5_DISPATCH_DELIVERED = "L5_DISPATCH_DELIVERED"
    L5_DISPATCH_RETRY_SCHEDULED = "L5_DISPATCH_RETRY_SCHEDULED"
    L5_DISPATCH_FAILED = "L5_DISPATCH_FAILED"
    REPLAY_TRIGGERED = "REPLAY_TRIGGERED"


class ConnectionStatus(StrEnum):
    """Lifecycle status of an external Connection aggregate."""

    PENDING_AUTH = "PENDING_AUTH"
    ACTIVE = "ACTIVE"
    ERROR = "ERROR"
    DEACTIVATED = "DEACTIVATED"


class AuthType(StrEnum):
    """Authentication strategies supported by external connectors."""

    NO_AUTH = "NO_AUTH"
    BASIC_AUTH = "BASIC_AUTH"
    BEARER_TOKEN = "BEARER_TOKEN"  # noqa: S105 - Enum constant for Bearer token auth strategy, not a secret
    API_KEY = "API_KEY"
    OAUTH2 = "OAUTH2"
    OAUTH2_CLIENT_CREDENTIALS = "OAUTH2_CLIENT_CREDENTIALS"
    MTLS = "MTLS"
    CUSTOM = "CUSTOM"


class ApiKeyPlacement(StrEnum):
    """Location where API key credentials must be injected in outgoing HTTP requests."""

    HEADER = "HEADER"
    QUERY_PARAM = "QUERY_PARAM"


class SyncMode(StrEnum):
    """Replication synchronization strategy for stream extraction."""

    FULL_REFRESH = "FULL_REFRESH"
    INCREMENTAL = "INCREMENTAL"


class PropertyType(StrEnum):
    """Dynamic UI input types for self-service connector configuration schemas."""

    SHORT_TEXT = "shortText"
    SECRET_TEXT = "secretText"  # noqa: S105 - UI schema property type identifier, not a password credential
    DROPDOWN = "dropdown"
    OAUTH2 = "oauth2"
    NUMBER = "number"
    BOOLEAN = "boolean"


class PaginationType(StrEnum):
    """Pagination strategies for Declarative HTTP APIs."""

    NONE = "none"
    OFFSET_LIMIT = "offset_limit"
    PAGE_NUMBER = "page_number"
    CURSOR = "cursor"
    LINK_HEADER = "link_header"


class OutboundDispatchStatus(StrEnum):
    """Lifecycle status of an external outbound dispatch execution."""

    PENDING = "PENDING"
    IN_FLIGHT = "IN_FLIGHT"
    DELIVERED = "DELIVERED"
    FAILED = "FAILED"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"


class PipelineLayer(StrEnum):
    """Five-stage SEDA execution pipeline layers."""

    L1_INGEST = "L1_INGEST"
    L2_REPLICA = "L2_REPLICA"
    L3_NORMALIZE = "L3_NORMALIZE"
    L4_HYDRATE = "L4_HYDRATE"
    L5_DELIVER = "L5_DELIVER"


class TimelineStatus(StrEnum):
    """Operational execution status recorded in the customer support timeline ledger."""

    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    RETRIED = "RETRIED"


class IpEventType(StrEnum):
    """Canonical domain event types emitted by the Integration Platform."""

    CONNECTION_CREATED = "ip.connection.created"
    CONNECTION_ACTIVATED = "ip.connection.activated"
    CONNECTION_DEACTIVATED = "ip.connection.deactivated"
    CONNECTION_RELINKED = "ip.connection.relinked"
    CONNECTION_ERROR_RECORDED = "ip.connection.error_recorded"
    INBOUND_RECORD_CREATED = "ip.inbound_record.created"
    SYNC_RUN_STARTED = "ip.sync_run.started"
    SYNC_RUN_COMPLETED = "ip.sync_run.completed"
    SYNC_RUN_FAILED = "ip.sync_run.failed"
    GENERATION_COMPLETED = "ip.generation.completed"
    FETCH_RECORD_REQUESTED = "ip.fetch_record.requested"
    REPLICA_RECORD_CHANGED = "ip.replica_record.changed"
    NORMALIZED_RECORD_CREATED = "ip.normalized_record.created"
    OUTBOUND_RECORD_CREATED = "ip.outbound_record.created"
    STREAM_STATE_CHECKPOINTED = "ip.stream_state.checkpointed"


class IngestionMode(StrEnum):
    """Strategy and mode used to capture an inbound record."""

    PULL_INITIAL = "PULL_INITIAL"
    PULL_INCREMENTAL = "PULL_INCREMENTAL"
    PULL_FULL_REFRESH = "PULL_FULL_REFRESH"
    PULL_RECONCILIATION = "PULL_RECONCILIATION"
    PUSH_FULL = "PUSH_FULL"
    PUSH_THIN = "PUSH_THIN"
    FETCH_ON_NOTIFY = "FETCH_ON_NOTIFY"
    STREAM_SUBSCRIBE = "STREAM_SUBSCRIBE"


class SyncRunKind(StrEnum):
    """Execution mode of a Pull sync run."""

    INITIAL = "INITIAL"
    INCREMENTAL = "INCREMENTAL"
    FULL_REFRESH = "FULL_REFRESH"
    RECONCILIATION = "RECONCILIATION"


class SyncRunStatus(StrEnum):
    """Lifecycle state machine for a Pull sync run."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class CursorKind(StrEnum):
    """Data type of the replication cursor field."""

    DATETIME = "DATETIME"
    INTEGER = "INTEGER"
    STRING = "STRING"


class RejectionReason(StrEnum):
    """Reason code for why a record was rejected during extraction."""

    MISSING_PRIMARY_KEY = "MISSING_PRIMARY_KEY"
    EMPTY_PRIMARY_KEY = "EMPTY_PRIMARY_KEY"
    INVALID_CURSOR = "INVALID_CURSOR"
    NOT_AN_OBJECT = "NOT_AN_OBJECT"
    EXTRACTION_FAILED = "EXTRACTION_FAILED"


class MergeOutcome(StrEnum):
    """Result of evaluating an incoming record against the current replica state."""

    INSERT = "INSERT"
    UPDATE = "UPDATE"
    NOOP = "NOOP"
    STALE = "STALE"
    TOMBSTONE = "TOMBSTONE"


class HttpWriteOperation(StrEnum):
    """Supported outbound write operations for generic HTTP streams."""

    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"


class FailureDisposition(StrEnum):
    """Actionable engine disposition indicating how upstream workflows should handle this failure."""

    RETRY = "RETRY"  # Transient fault: retry with backoff or NACK message
    FAIL = "FAIL"  # Terminal/configuration fault: stop, dead-letter, alert user
    IGNORE = "IGNORE"  # Benign fault: log and skip without aborting


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
