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
    L3_REJECTED = "L3_REJECTED"
    L3_NORMALIZATION_FAILED = "L3_NORMALIZATION_FAILED"
    L3_SKIPPED_STALE = "L3_SKIPPED_STALE"
    L3_TOMBSTONED = "L3_TOMBSTONED"
    L3_REFERENCE_PENDING = "L3_REFERENCE_PENDING"
    L3_REFERENCE_RESOLVED = "L3_REFERENCE_RESOLVED"
    L4_DOMAIN_HYDRATED = "L4_DOMAIN_HYDRATED"
    L5_DISPATCH_PENDING = "L5_DISPATCH_PENDING"
    L5_DISPATCH_DELIVERED = "L5_DISPATCH_DELIVERED"
    L5_DISPATCH_RETRY_SCHEDULED = "L5_DISPATCH_RETRY_SCHEDULED"
    L5_DISPATCH_FAILED = "L5_DISPATCH_FAILED"
    REPLAY_TRIGGERED = "REPLAY_TRIGGERED"
    MODIFIED_AND_REPLAYED = "MODIFIED_AND_REPLAYED"


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
    SYNC_RUN_REQUESTED = "ip.sync_run.requested"
    SYNC_RUN_STARTED = "ip.sync_run.started"
    SYNC_RUN_COMPLETED = "ip.sync_run.completed"
    SYNC_RUN_FAILED = "ip.sync_run.failed"
    GENERATION_COMPLETED = "ip.generation.completed"
    FETCH_RECORD_REQUESTED = "ip.fetch_record.requested"
    REPLICA_RECORD_CHANGED = "ip.replica_record.changed"
    NORMALIZED_RECORD_CREATED = "ip.normalized_record.created"
    CANONICAL_RECORD_CHANGED = "ip.canonical_record.changed"
    TRANSFORMATION_CHANGED = "ip.transformation.changed"
    TRANSFORMATION_VERSION_PROMOTED = "ip.transformation_version.promoted"
    STITCH_REGISTERED = "ip.stitch.registered"
    OUTBOUND_RECORD_CREATED = "ip.outbound_record.created"
    STREAM_STATE_CHECKPOINTED = "ip.stream_state.checkpointed"


class IpIdPrefix(StrEnum):
    """Domain-specific entity ID prefixes for the Integration Platform (IP) bounded context."""

    TRACE = "ip_trc"
    TRACE_EVENT = "ip_trace_evt"
    INBOUND_RECORD = "ip_inb"
    CONNECTION = "ip_conn"
    CATALOG = "ip_cat"
    STREAM = "ip_strm"
    REPLICA = "ip_rep"
    REPLICA_REJECTION = "ip_rej"
    NORMALIZED = "ip_nrm"
    CANONICAL = "ip_canon"
    OUTBOUND_RECORD = "ip_out"
    OUTBOUND_DISPATCH = "ip_disp"
    OUTBOX = "ip_obx"
    GEM = "ip_gem"
    STREAM_STATE = "ip_cst"
    MDM_READING = "ip_mdmr"
    MDM_SERVICE_POINT = "ip_mdms"
    TMS_LOAD = "ip_tmsl"
    TMS_CARRIER = "ip_tmsc"
    SYNC_RUN = "ip_sync"
    TRANSFORMATION = "ip_xfrm"
    STITCH = "ip_stch"
    NORMALIZATION_LEDGER = "ip_nlg"
    NORMALIZATION_REJECTION = "ip_nrj"
    SHADOW_DIFF = "ip_sdiff"
    PENDING_REFERENCE = "ip_pref"


class TransformationMode(StrEnum):
    """Execution mode of a stream transformation."""

    ACTIVE = "ACTIVE"
    SHADOW = "SHADOW"
    DISABLED = "DISABLED"


class NormalizationOutcome(StrEnum):
    """Result of normalizing an L2 replica snapshot into canonical domain records."""

    NORMALIZED = "NORMALIZED"
    REJECTED = "REJECTED"
    SKIPPED_STALE = "SKIPPED_STALE"
    TOMBSTONED = "TOMBSTONED"
    SKIPPED_NO_TRANSFORMATION = "SKIPPED_NO_TRANSFORMATION"


class RuleSeverity(StrEnum):
    """Action severity for a canonical entity quality validation rule."""

    REJECT = "REJECT"
    FLAG = "FLAG"


class NormalizationRejectionReason(StrEnum):
    """Typed failure code for a canonical transformation or validation rejection."""

    MISSING_REQUIRED_FIELD = "MISSING_REQUIRED_FIELD"
    SCHEMA_VALIDATION_FAILED = "SCHEMA_VALIDATION_FAILED"
    QUALITY_RULE_REJECTED = "QUALITY_RULE_REJECTED"
    TRANSFORMER_ERROR = "TRANSFORMER_ERROR"
    UNRESOLVED_REFERENCE = "UNRESOLVED_REFERENCE"
    MISSING_TRANSFORMATION = "MISSING_TRANSFORMATION"


class PendingReferenceStatus(StrEnum):
    """Resolution status of a late-arriving canonical source reference."""

    PENDING = "PENDING"
    RESOLVED = "RESOLVED"


class CanonicalAction(StrEnum):
    """Mutation action applied to a canonical domain record."""

    UPSERT = "UPSERT"
    TOMBSTONE = "TOMBSTONE"


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
    SKIPPED_ALREADY_ACTIVE = "SKIPPED_ALREADY_ACTIVE"


class FetchRecordStatus(StrEnum):
    """Execution status of a Layer-1 Fetch-on-Notify single-record pull."""

    FETCHED = "FETCHED"
    DEDUPLICATED = "DEDUPLICATED"
    NOT_FOUND = "NOT_FOUND"
    RATE_LIMITED = "RATE_LIMITED"
    TRANSIENT_ERROR = "TRANSIENT_ERROR"
    FETCH_FAILED = "FETCH_FAILED"
    TERMINAL_ERROR = "TERMINAL_ERROR"


class SyncErrorCode(StrEnum):
    """Error classification code emitted by Layer-1 Pull Sync runs."""

    RATE_LIMITED = "RATE_LIMITED"
    TRANSIENT_ERROR = "TRANSIENT_ERROR"
    UPSTREAM_5XX = "UPSTREAM_5XX"
    AUTH_EXPIRED = "AUTH_EXPIRED"
    TERMINAL_ERROR = "TERMINAL_ERROR"


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


class ReplayStage(StrEnum):
    """Target execution stage for deterministic transaction replay."""

    RETRY_INGEST = "RETRY_INGEST"
    RETRY_NORMALIZE = "RETRY_NORMALIZE"
    RETRY_STITCH = "RETRY_STITCH"
    RETRY_DELIVER = "RETRY_DELIVER"


class IpOutboxSource(StrEnum):
    """Canonical CloudEvents source identifiers for IP outbox streams."""

    CONTROL_PLANE = "soopa.ip.control_plane"
    DATA_PLANE = "soopa.ip.data_plane"


class IpOutboxChannel(StrEnum):
    """PostgreSQL LISTEN/NOTIFY channel names for IP outbox wakeup."""

    CONTROL_PLANE = "ip_cp_outbox_channel"
    DATA_PLANE = "ip_dp_outbox_channel"


class IpJobName(StrEnum):
    """Scheduled background job identifiers for IP Control Plane and Data Plane."""

    IP_CONTROL_PLANE_OUTBOX_SWEEPER = "IP_CONTROL_PLANE_OUTBOX_SWEEPER"
    IP_CONTROL_PLANE_OUTBOX_CLEANUP = "IP_CONTROL_PLANE_OUTBOX_CLEANUP"
    IP_DATA_PLANE_OUTBOX_SWEEPER = "IP_DATA_PLANE_OUTBOX_SWEEPER"
    IP_DATA_PLANE_OUTBOX_CLEANUP = "IP_DATA_PLANE_OUTBOX_CLEANUP"
    IP_DATA_RETENTION_CLEANUP = "IP_DATA_RETENTION_CLEANUP"
