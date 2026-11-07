"""Domain events for Outbound delivery aggregates."""

from dataclasses import dataclass

from seedwork.events import DomainEvent, EventProcessingLane

from ip.engine.domain.enums import IpEventType


@dataclass(frozen=True)
class OutboundRecordCreatedEvent(DomainEvent):
    """Domain event emitted when one or more external outbound dispatches are staged or executed."""

    record_id: str = ""
    tenant_id: str = ""
    connection_id: str = ""
    app_id: str = ""
    trace_id: str = ""
    correlation_id: str | None = None
    stream_name: str = ""
    status: str = ""
    response_status_code: int | None = None
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
        return IpEventType.OUTBOUND_RECORD_CREATED

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id

    def get_trace_id(self) -> str | None:
        return self.trace_id or None

    def get_correlation_id(self) -> str | None:
        return self.correlation_id

    def get_processing_lane(self) -> EventProcessingLane:
        return self.lane or EventProcessingLane.REALTIME
