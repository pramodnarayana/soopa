"""Base class for all domain events in the UCP domain model."""

from abc import ABC

from pydantic import BaseModel


class DomainEvent(BaseModel, ABC):
    """
    Marker base class for all domain events.

    Inheriting from Pydantic BaseModel ensures all events are serialisable
    to JSON for the Outbox pattern without any extra mapping step.
    """

    model_config = {"frozen": True}

    @property
    def event_name(self) -> str:
        """Returns the canonical event name for messaging (e.g. 'tenant.provisioned')."""
        raise NotImplementedError

    def get_routing_tenant_id(self) -> str | None:
        """
        Returns the tenant ID associated with this event for Outbox routing.
        If the event is platform-wide and has no tenant context, return None.
        """
        raise NotImplementedError
