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
    INBOUND_RECORD = "ip_inb"
    OUTBOUND_RECORD = "ip_out"
    TRACE = "ip_trc"
    GEM = "ip_gem"
    TIMELINE = "ip_tml"
    STREAM_STATE = "ip_cst"


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


class IpEventType(StrEnum):
    """Canonical domain event types emitted by the Integration Platform."""

    CONNECTION_CREATED = "ip.connection.created"
    CONNECTION_ACTIVATED = "ip.connection.activated"
    CONNECTION_DEACTIVATED = "ip.connection.deactivated"
    CONNECTION_RELINKED = "ip.connection.relinked"
    CONNECTION_ERROR_RECORDED = "ip.connection.error_recorded"
    INBOUND_RECORD_CREATED = "ip.inbound_record.created"
    OUTBOUND_RECORD_CREATED = "ip.outbound_record.created"
    STREAM_STATE_CHECKPOINTED = "ip.stream_state.checkpointed"
