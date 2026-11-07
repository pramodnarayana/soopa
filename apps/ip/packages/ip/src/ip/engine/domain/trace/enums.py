"""Audit trace enumerations for the IP Distributed Tracing & Audit Ledger."""

from enum import StrEnum

from ip.engine.domain.dispatch.enums import OutboundDispatchStatus
from ip.engine.domain.enums import PipelineStage


class TraceEventStatus(StrEnum):
    """Execution status recorded for a trace event in the audit trace ledger."""

    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    RETRIED = "RETRIED"


class IpTraceStatus(StrEnum):
    """End-to-end lifecycle status of a record trace across IP pipeline stages."""

    INGESTED = "INGESTED"
    REPLICATED = "REPLICATED"
    NORMALIZED = "NORMALIZED"
    REJECTED = "REJECTED"
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    RETRY_SCHEDULED = "RETRY_SCHEDULED"
    FAILED = "FAILED"
    DEAD_LETTERED = "DEAD_LETTERED"
    RECEIVED = "RECEIVED"
    PROCESSED = "PROCESSED"
    UNKNOWN = "UNKNOWN"


class IpTraceEventType(StrEnum):
    """Canonical trace event types recorded in the TracedAggregateRoot audit ledger."""

    # Ingest Stage
    INGEST_RECEIVED = "INGEST_RECEIVED"
    INGEST_FAILED = "INGEST_FAILED"
    PULL_PAGE_RECEIVED = "PULL_PAGE_RECEIVED"
    PUSH_RECEIVED = "PUSH_RECEIVED"
    PUSH_REJECTED = "PUSH_REJECTED"
    FETCH_COMPLETED = "FETCH_COMPLETED"

    # Replica Stage
    REPLICA_CREATED = "REPLICA_CREATED"
    REPLICA_UPDATED = "REPLICA_UPDATED"
    REPLICA_UNCHANGED = "REPLICA_UNCHANGED"
    REPLICA_TOMBSTONED = "REPLICA_TOMBSTONED"
    EXTRACTION_REJECTED = "EXTRACTION_REJECTED"

    # Normalize Stage
    NORMALIZED = "NORMALIZED"
    NORMALIZATION_REJECTED = "NORMALIZATION_REJECTED"
    NORMALIZATION_FAILED = "NORMALIZATION_FAILED"
    SKIPPED_STALE = "SKIPPED_STALE"
    TOMBSTONED = "TOMBSTONED"
    REFERENCE_PENDING = "REFERENCE_PENDING"
    REFERENCE_RESOLVED = "REFERENCE_RESOLVED"

    # Hydrate Stage
    DOMAIN_HYDRATED = "DOMAIN_HYDRATED"

    # Delivery / Dispatch Stage
    DISPATCH_PENDING = "DISPATCH_PENDING"
    DISPATCH_DELIVERED = "DISPATCH_DELIVERED"
    DISPATCH_RETRY_SCHEDULED = "DISPATCH_RETRY_SCHEDULED"
    DISPATCH_FAILED = "DISPATCH_FAILED"

    # Stage Replay
    REPLAY_TRIGGERED = "REPLAY_TRIGGERED"
    MODIFIED_AND_REPLAYED = "MODIFIED_AND_REPLAYED"


def map_outbound_status_to_trace_status(status: OutboundDispatchStatus | str) -> IpTraceStatus:
    """Maps an L5 OutboundDispatchStatus token to its corresponding IpTraceStatus."""
    resolved = (
        status if isinstance(status, OutboundDispatchStatus) else OutboundDispatchStatus(status)
    )
    if resolved is OutboundDispatchStatus.IN_FLIGHT:
        return IpTraceStatus.PENDING
    return IpTraceStatus(resolved.value)


__all__ = [
    "IpTraceEventType",
    "IpTraceStatus",
    "PipelineStage",
    "TraceEventStatus",
    "map_outbound_status_to_trace_status",
]
