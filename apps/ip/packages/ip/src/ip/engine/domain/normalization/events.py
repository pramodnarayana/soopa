"""Domain events for canonical transformation and normalization aggregates."""

from dataclasses import dataclass

from seedwork.events import DomainEvent, EventProcessingLane

from ip.engine.domain.enums import IpEventType


@dataclass(frozen=True)
class NormalizedRecordCreatedEvent(DomainEvent):
    """Domain event emitted when an L3 canonical normalization completes."""

    record_id: str = ""
    tenant_id: str = ""
    connection_id: str = ""
    canonical_type: str = ""
    source_id: str = ""
    trace_id: str = ""
    correlation_id: str | None = None
    parent_trace_id: str | None = None
    original_trace_id: str | None = None
    replay_count: int = 0
    record_ids: tuple[str, ...] = ()
    lane: EventProcessingLane | None = None

    def __post_init__(self) -> None:
        if not self.record_ids and self.record_id:
            object.__setattr__(self, "record_ids", (self.record_id,))
        elif self.record_ids and not self.record_id:
            object.__setattr__(self, "record_id", self.record_ids[0])
        if self.lane is None:
            resolved_lane = (
                EventProcessingLane.BULK
                if len(self.record_ids) > 1
                else EventProcessingLane.REALTIME
            )
            object.__setattr__(self, "lane", resolved_lane)

    @property
    def event_name(self) -> str:
        return IpEventType.NORMALIZED_RECORD_CREATED

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id

    def get_trace_id(self) -> str | None:
        return self.trace_id or None

    def get_correlation_id(self) -> str | None:
        return self.correlation_id

    def get_processing_lane(self) -> EventProcessingLane:
        return self.lane or EventProcessingLane.REALTIME


@dataclass(frozen=True)
class CanonicalRecordChangedEvent(DomainEvent):
    """Domain event emitted when one or more canonical domain records are upserted or tombstoned."""

    tenant_id: str = ""
    connection_id: str = ""
    canonical_type: str = ""
    source_id: str = ""
    action: str = "UPSERT"
    trace_id: str = ""
    transformation_id: str = ""
    transformation_version: int = 1
    replica_id: str = ""
    replica_version: int = 1
    correlation_id: str | None = None
    changed_fields: tuple[str, ...] = ()
    parent_trace_id: str | None = None
    original_trace_id: str | None = None
    replay_count: int = 0
    record_ids: tuple[str, ...] = ()
    lane: EventProcessingLane | None = None

    def __post_init__(self) -> None:
        if not self.record_ids and self.source_id:
            object.__setattr__(self, "record_ids", (self.source_id,))
        elif self.record_ids and not self.source_id:
            object.__setattr__(self, "source_id", self.record_ids[0])
        if self.lane is None:
            resolved_lane = (
                EventProcessingLane.BULK
                if len(self.record_ids) > 1
                else EventProcessingLane.REALTIME
            )
            object.__setattr__(self, "lane", resolved_lane)

    @property
    def event_name(self) -> str:
        return IpEventType.CANONICAL_RECORD_CHANGED

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id

    def get_trace_id(self) -> str | None:
        return self.trace_id or None

    def get_correlation_id(self) -> str | None:
        return self.correlation_id

    def get_processing_lane(self) -> EventProcessingLane:
        return self.lane or EventProcessingLane.REALTIME


@dataclass(frozen=True)
class TransformationChangedEvent(DomainEvent):
    """Domain event emitted when a stream transformation is created or updated."""

    id: str
    tenant_id: str
    connection_id: str
    stream: str
    transformation_id: str
    transformation_version: int
    mode: str
    shadow_transformation_version: int | None = None

    @property
    def event_name(self) -> str:
        return IpEventType.TRANSFORMATION_CHANGED

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id

    def get_processing_lane(self) -> EventProcessingLane:
        return EventProcessingLane.BULK


@dataclass(frozen=True)
class TransformationVersionPromotedEvent(DomainEvent):
    """Domain event emitted when a candidate shadow transformation version is promoted to active."""

    id: str
    tenant_id: str
    connection_id: str
    stream: str
    transformation_id: str
    promoted_version: int
    previous_version: int

    @property
    def event_name(self) -> str:
        return IpEventType.TRANSFORMATION_VERSION_PROMOTED

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id

    def get_processing_lane(self) -> EventProcessingLane:
        return EventProcessingLane.BULK
