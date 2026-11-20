"""Domain events for the Stitch workflow aggregate."""

from dataclasses import dataclass

from seedwork.events import DomainEvent, EventProcessingLane

from ip.engine.domain.enums import IpEventType


@dataclass(frozen=True)
class StitchRegisteredEvent(DomainEvent):
    """Domain event emitted when a Stitch is registered or updated in the Control Plane."""

    stitch_id: str
    tenant_id: str
    canonical_event_type: str
    target_workflow_id: str
    is_active: bool

    @property
    def event_name(self) -> str:
        return IpEventType.STITCH_REGISTERED

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id

    def get_processing_lane(self) -> EventProcessingLane:
        return EventProcessingLane.BULK


@dataclass(frozen=True)
class StitchUpdatedEvent(DomainEvent):
    """Domain event emitted when a Stitch configuration or activation state is updated."""

    stitch_id: str
    tenant_id: str
    canonical_event_type: str
    target_workflow_id: str
    is_active: bool

    @property
    def event_name(self) -> str:
        return IpEventType.STITCH_UPDATED

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id

    def get_processing_lane(self) -> EventProcessingLane:
        return EventProcessingLane.BULK


@dataclass(frozen=True)
class StitchDeletedEvent(DomainEvent):
    """Domain event emitted when a Stitch is deleted from the Control Plane."""

    stitch_id: str
    tenant_id: str
    target_workflow_id: str

    @property
    def event_name(self) -> str:
        return IpEventType.STITCH_DELETED

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id

    def get_processing_lane(self) -> EventProcessingLane:
        return EventProcessingLane.BULK


@dataclass(frozen=True)
class StitchTaskConfigSavedEvent(DomainEvent):
    """Domain event emitted when a Stitch task runtime policy is configured or updated."""

    config_id: str
    tenant_id: str
    stitch_id: str
    node_key: str
    timeout_seconds: int
    max_attempts: int
    max_in_flight_tasks: int
    queue_name: str

    @property
    def event_name(self) -> str:
        return IpEventType.STITCH_TASK_CONFIG_SAVED

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id

    def get_processing_lane(self) -> EventProcessingLane:
        return EventProcessingLane.BULK


@dataclass(frozen=True)
class StitchTaskConfigDeletedEvent(DomainEvent):
    """Domain event emitted when a Stitch task runtime policy is deleted."""

    config_id: str
    tenant_id: str
    stitch_id: str
    node_key: str

    @property
    def event_name(self) -> str:
        return IpEventType.STITCH_TASK_CONFIG_DELETED

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id

    def get_processing_lane(self) -> EventProcessingLane:
        return EventProcessingLane.BULK


__all__ = [
    "StitchDeletedEvent",
    "StitchRegisteredEvent",
    "StitchTaskConfigDeletedEvent",
    "StitchTaskConfigSavedEvent",
    "StitchUpdatedEvent",
]
