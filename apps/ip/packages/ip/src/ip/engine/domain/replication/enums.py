"""Replication, CDC, and ingestion domain enumerations."""

from enum import StrEnum


class SyncMode(StrEnum):
    """Synchronization strategy for stream records."""

    FULL_REFRESH = "FULL_REFRESH"
    INCREMENTAL = "INCREMENTAL"


class EntitySyncSchedule(StrEnum):
    """Cadence policy for automated pull synchronization of a subscribed connection entity."""

    MANUAL = "manual"
    EVERY_5M = "5m"
    EVERY_15M = "15m"
    HOURLY = "1h"
    EVERY_6H = "6h"
    DAILY = "24h"


class EntitySyncFrom(StrEnum):
    """Historical lookback boundary policy for a subscribed connection entity."""

    ALL = "all"
    LAST_24H = "24h"
    LAST_7D = "7d"
    LAST_30D = "30d"
    LAST_90D = "90d"
    CUSTOM = "custom"


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
    RETURN_LEG_CALLBACK = "RETURN_LEG_CALLBACK"


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
    BATCH_UPSERT = "BATCH_UPSERT"
