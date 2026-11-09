"""Domain events emitted by the High-Frequency Interval Data Plane."""

from dataclasses import dataclass

from seedwork.events import DomainEvent, EventProcessingLane

from ip.engine.domain.enums import IpEventType
from ip.engine.domain.intervals.enums import PriorityLane


@dataclass(frozen=True)
class IntervalBatchIngestedEvent(DomainEvent):
    """Emitted when an L1 raw interval macro-batch is buffered to S3 and registered in ip_batch_manifests."""

    batch_id: str = ""
    tenant_id: str = ""
    connection_id: str = ""
    app_id: str = ""
    stream_name: str = ""
    l1_raw_uri: str = ""
    payload_sha256: str = ""
    payload_format: str = "JSON_ARRAY"
    raw_ingested_count: int = 0
    priority_lane: str = PriorityLane.P1_LIVE.value
    window_start_utc: str = ""
    window_end_utc: str = ""
    trace_id: str = ""
    correlation_id: str | None = None

    @property
    def event_name(self) -> str:
        return IpEventType.INTERVAL_BATCH_INGESTED

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id

    def get_trace_id(self) -> str | None:
        return self.trace_id or None

    def get_correlation_id(self) -> str | None:
        return self.correlation_id

    def get_processing_lane(self) -> EventProcessingLane:
        if self.priority_lane == PriorityLane.P0_CRITICAL.value:
            return EventProcessingLane.REALTIME
        return EventProcessingLane.BULK


@dataclass(frozen=True)
class IntervalBatchProcessedEvent(DomainEvent):
    """Emitted when an interval batch completes vectorized L2/L3 normalization and Zero-Loss reconciliation."""

    batch_id: str = ""
    tenant_id: str = ""
    connection_id: str = ""
    stream_name: str = ""
    raw_ingested_count: int = 0
    duplicates_dropped_count: int = 0
    valid_canonical_count: int = 0
    quarantined_held_count: int = 0
    promoted_outage_clusters_count: int = 0
    l2_replica_uri: str | None = None
    l3_canonical_uri: str | None = None
    trace_id: str = ""
    correlation_id: str | None = None

    @property
    def event_name(self) -> str:
        return IpEventType.INTERVAL_BATCH_PROCESSED

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id

    def get_trace_id(self) -> str | None:
        return self.trace_id or None

    def get_correlation_id(self) -> str | None:
        return self.correlation_id

    def get_processing_lane(self) -> EventProcessingLane:
        return EventProcessingLane.BULK


@dataclass(frozen=True)
class FeederOutageClusterDetectedEvent(DomainEvent):
    """Storm-safe promoted event bridged to the P0_CRITICAL real-time lane upon clustered 0.0V readings."""

    cluster_id: str = ""
    tenant_id: str = ""
    connection_id: str = ""
    batch_id: str = ""
    feeder_id: str = ""
    substation_id: str = ""
    outage_meter_count: int = 0
    affected_meter_ids: tuple[str, ...] = ()
    outage_start_utc: str = ""
    trace_id: str = ""
    correlation_id: str | None = None

    @property
    def event_name(self) -> str:
        return IpEventType.FEEDER_OUTAGE_DETECTED

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id

    def get_trace_id(self) -> str | None:
        return self.trace_id or None

    def get_correlation_id(self) -> str | None:
        return self.correlation_id

    def get_processing_lane(self) -> EventProcessingLane:
        return EventProcessingLane.REALTIME


__all__ = [
    "FeederOutageClusterDetectedEvent",
    "IntervalBatchIngestedEvent",
    "IntervalBatchProcessedEvent",
]
