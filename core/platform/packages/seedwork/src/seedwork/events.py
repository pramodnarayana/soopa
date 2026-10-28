from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum

from seedwork.domain.types import JsonDict
from seedwork.id_registry import SystemIdPrefix
from seedwork.utils import generate_id


class EventProcessingLane(StrEnum):
    """Standard enterprise event processing lane separating realtime interactive vs bulk workloads."""

    REALTIME = "realtime"
    BULK = "bulk"


@dataclass(frozen=True)
class EventEnvelope:
    """
    Standard Enterprise Event Envelope (CloudEvents 1.0 compliant).
    Must be used by all Bounded Contexts when publishing events via the Outbox
    and when consuming events via EventEnvelopeDispatcher.
    """

    id: str
    source: str
    event_type: str
    tenant_id: str | None
    idempotency_key: str | None
    payload: JsonDict
    trace_id: str | None = None
    correlation_id: str | None = None
    lane: EventProcessingLane = EventProcessingLane.REALTIME


@dataclass(frozen=True)
class DomainEvent(ABC):
    """
    Marker base class for all domain events.

    Events are immutable dataclasses serialized for the Outbox pattern by the
    shared domain-event serializer.
    """

    idempotency_key: str = field(
        default_factory=lambda: generate_id(SystemIdPrefix.IDEMPOTENCY), kw_only=True
    )

    @property
    @abstractmethod
    def event_name(self) -> str:
        """Returns the canonical event name for messaging (e.g. 'tenant.provisioned')."""
        raise NotImplementedError

    @abstractmethod
    def get_routing_tenant_id(self) -> str | None:
        """
        Returns the tenant ID associated with this event for Outbox routing.
        If the event is platform-wide and has no tenant context, return None.
        """
        raise NotImplementedError

    def get_trace_id(self) -> str | None:
        """Returns the distributed trace_id associated with this event, if any."""
        return None

    def get_correlation_id(self) -> str | None:
        """Returns the business correlation_id associated with this event, if any."""
        return None

    def get_processing_lane(self) -> EventProcessingLane:
        """Returns the event processing lane (REALTIME or BULK) for this event."""
        return EventProcessingLane.REALTIME
