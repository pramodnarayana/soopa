from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class DomainEvent(ABC):
    """
    Marker base class for all domain events.

    Events are immutable dataclasses serialized for the Outbox pattern by the
    shared domain-event serializer.
    """

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

    @property
    def idempotency_key(self) -> str:
        """
        Returns the idempotency key for this event.
        Defaults to the event id if present, else a newly generated UUID.
        """
        if hasattr(self, "id"):
            return str(self.id)
        if not hasattr(self, "_idempotency_key"):
            import uuid

            object.__setattr__(self, "_idempotency_key", str(uuid.uuid4()))
        return self._idempotency_key
