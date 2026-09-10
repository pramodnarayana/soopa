from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from seedwork.constants import SystemIdPrefix
from seedwork.domain.types import JsonDict
from seedwork.utils import generate_id


@dataclass(frozen=True)
class EventEnvelope:
    """
    Standard Enterprise Event Envelope (CloudEvents compliant).
    Must be used by all Bounded Contexts when publishing events via the Outbox.
    """

    id: str
    source: str
    event_type: str
    tenant_id: str | None
    idempotency_key: str | None
    payload: JsonDict


@dataclass(frozen=True)
class DomainEvent(ABC):
    """
    Marker base class for all domain events.

    Events are immutable dataclasses serialized for the Outbox pattern by the
    shared domain-event serializer.
    """

    idempotency_key: str = field(
        default_factory=lambda: generate_id(SystemIdPrefix.GENERIC), kw_only=True
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
