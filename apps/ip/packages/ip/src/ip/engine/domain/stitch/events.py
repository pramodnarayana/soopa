"""Domain events for the Stitch workflow aggregate."""

from dataclasses import dataclass

from seedwork.events import DomainEvent, EventProcessingLane

from ip.engine.domain.enums import IpEventType


@dataclass(frozen=True)
class StitchRegisteredEvent(DomainEvent):
    """Domain event emitted when a Stitch is registered or updated in the Control Plane."""

    stitch_id: str
    tenant_id: str
    workflow_id: str
    workflow_version: int
    canonical_event_type: str
    is_trigger: bool
    is_active: bool

    @property
    def event_name(self) -> str:
        return IpEventType.STITCH_REGISTERED

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id

    def get_processing_lane(self) -> EventProcessingLane:
        return EventProcessingLane.BULK
