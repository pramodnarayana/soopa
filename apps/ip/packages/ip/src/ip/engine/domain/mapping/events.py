"""Domain events for the MappingSpec aggregate."""

from __future__ import annotations

from dataclasses import dataclass

from seedwork.events import DomainEvent, EventProcessingLane

from ip.engine.domain.enums import IpEventType


@dataclass(frozen=True)
class MappingSpecSavedEvent(DomainEvent):
    """Domain event emitted when a MappingSpec is created or updated in the Control Plane."""

    mapping_spec_id: str
    tenant_id: str
    name: str
    source_type: str
    target_connection_id: str
    target_entity_name: str
    version: int
    is_active: bool

    @property
    def event_name(self) -> str:
        return IpEventType.MAPPING_SPEC_SAVED

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id

    def get_processing_lane(self) -> EventProcessingLane:
        return EventProcessingLane.BULK


@dataclass(frozen=True)
class MappingSpecDeletedEvent(DomainEvent):
    """Domain event emitted when a MappingSpec is deleted from the Control Plane."""

    mapping_spec_id: str
    tenant_id: str
    name: str

    @property
    def event_name(self) -> str:
        return IpEventType.MAPPING_SPEC_DELETED

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id

    def get_processing_lane(self) -> EventProcessingLane:
        return EventProcessingLane.BULK
