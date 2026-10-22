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


class IpDomainIdPrefix(StrEnum):
    """Domain-specific ID prefixes for the Integration Platform bounded context."""

    CONNECTION = "ip_conn"
    CATALOG = "ip_cat"
    STREAM = "ip_strm"
    REPLICA = "ip_rep"
    NORMALIZED = "ip_nrm"
    INBOUND_RECORD = "ip_inb"
    OUTBOUND_RECORD = "ip_out"
    OUTBOX = "ip_obx"
    TRACE = "ip_trc"
    TRACE_EVENT = "ip_trace_evt"
    GEM = "ip_gem"
    TIMELINE = "ip_trace_evt"
    STREAM_STATE = "ip_cst"
    MDM_READING = "ip_mdmr"
    MDM_SERVICE_POINT = "ip_mdms"
    TMS_LOAD = "ip_tmsl"
    TMS_CARRIER = "ip_tmsc"


class IpTraceEventType(StrEnum):
    """Canonical trace event types recorded in the TracedAggregateRoot audit ledger."""

    L1_INGEST_RECEIVED = "L1_INGEST_RECEIVED"
    L1_INGEST_FAILED = "L1_INGEST_FAILED"
    L2_REPLICA_CREATED = "L2_REPLICA_CREATED"
    L2_REPLICA_UPDATED = "L2_REPLICA_UPDATED"
    L2_REPLICA_UNCHANGED = "L2_REPLICA_UNCHANGED"
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


class NormalizedEntityType(StrEnum):
    """Canonical domain entity types supported across IP application verticals."""

    MDM_METER_READING = "MDM_METER_READING"
    MDM_SERVICE_POINT = "MDM_SERVICE_POINT"
    TMS_LOAD = "TMS_LOAD"
    TMS_CARRIER = "TMS_CARRIER"


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
    REPLICA_RECORD_UPDATED = "ip.replica_record.updated"
    NORMALIZED_RECORD_CREATED = "ip.normalized_record.created"
    OUTBOUND_RECORD_CREATED = "ip.outbound_record.created"
    STREAM_STATE_CHECKPOINTED = "ip.stream_state.checkpointed"
