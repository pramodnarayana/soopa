"""Pure domain events for the Webhook Ingress bounded context."""

from __future__ import annotations

from dataclasses import dataclass

from seedwork.events import DomainEvent

from ip.engine.domain.enums import IpEventType


@dataclass(frozen=True)
class WebhookEndpointCreatedEvent(DomainEvent):
    """Emitted when a new WebhookEndpoint aggregate root is provisioned."""

    endpoint_id: str
    tenant_id: str
    endpoint_slug: str
    name: str
    verification_strategy: str
    bound_connection_id: str | None = None

    @property
    def event_name(self) -> str:
        return IpEventType.WEBHOOK_ENDPOINT_CREATED.value

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class WebhookEndpointUpdatedEvent(DomainEvent):
    """Emitted when a WebhookEndpoint's metadata is updated."""

    endpoint_id: str
    tenant_id: str
    endpoint_slug: str
    name: str
    bound_connection_id: str | None = None

    @property
    def event_name(self) -> str:
        return IpEventType.WEBHOOK_ENDPOINT_UPDATED.value

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class WebhookSecretRotatedEvent(DomainEvent):
    """Emitted when an endpoint's secret is rotated."""

    endpoint_id: str
    tenant_id: str
    endpoint_slug: str
    secret_rotated_at: str

    @property
    def event_name(self) -> str:
        return IpEventType.WEBHOOK_SECRET_ROTATED.value

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class WebhookEndpointDeactivatedEvent(DomainEvent):
    """Emitted when a WebhookEndpoint is deactivated."""

    endpoint_id: str
    tenant_id: str
    endpoint_slug: str

    @property
    def event_name(self) -> str:
        return IpEventType.WEBHOOK_ENDPOINT_DEACTIVATED.value

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id


@dataclass(frozen=True)
class WebhookEventRouteAddedEvent(DomainEvent):
    """Emitted when a new multiplexed event route is attached to a WebhookEndpoint."""

    endpoint_id: str
    tenant_id: str
    route_id: str
    event_pattern: str
    payload_semantic: str
    target_pipeline_or_workflow_id: str
    priority: int = 100

    @property
    def event_name(self) -> str:
        return IpEventType.WEBHOOK_EVENT_ROUTE_ADDED.value

    def get_routing_tenant_id(self) -> str | None:
        return self.tenant_id
