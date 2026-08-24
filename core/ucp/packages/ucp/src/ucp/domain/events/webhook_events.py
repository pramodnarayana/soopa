from dataclasses import dataclass
from typing import Any

from ucp.domain.events.base import DomainEvent


@dataclass(frozen=True)
class WebhookCreatedEvent(DomainEvent):
    """
    Emitted when a new Webhook is created.
    """

    tenant_id: str
    webhook_id: str
    event_type: str = "webhook.created"

    @property
    def event_name(self) -> str:
        return self.event_type

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "webhook_id": self.webhook_id,
            "event_type": self.event_type,
        }


@dataclass(frozen=True)
class WebhookUpdatedEvent(DomainEvent):
    """
    Emitted when a Webhook is updated.
    """

    tenant_id: str
    webhook_id: str
    event_type: str = "webhook.updated"

    @property
    def event_name(self) -> str:
        return self.event_type

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "webhook_id": self.webhook_id,
            "event_type": self.event_type,
        }


@dataclass(frozen=True)
class WebhookDeletedEvent(DomainEvent):
    """
    Emitted when a Webhook is deleted.
    """

    tenant_id: str
    webhook_id: str
    event_type: str = "webhook.deleted"

    @property
    def event_name(self) -> str:
        return self.event_type

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "tenant_id": self.tenant_id,
            "webhook_id": self.webhook_id,
            "event_type": self.event_type,
        }
