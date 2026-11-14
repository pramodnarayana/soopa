"""WebhookEndpoint Aggregate Root for the Integration Platform."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import ClassVar

from seedwork.domain.aggregate import AggregateRoot
from seedwork.utils import generate_id

from ip.engine.domain.enums import IpIdPrefix
from ip.engine.domain.webhook.enums import VerificationStrategy
from ip.engine.domain.webhook.events import (
    WebhookEndpointCreatedEvent,
    WebhookEndpointDeactivatedEvent,
    WebhookEndpointUpdatedEvent,
    WebhookEventRouteAddedEvent,
    WebhookSecretRotatedEvent,
)
from ip.engine.domain.webhook.route import WebhookEventRoute


@dataclass(kw_only=True, eq=False)
class WebhookEndpoint(AggregateRoot):
    """Aggregate Root representing a provisioned passive inbound webhook endpoint."""

    ID_PREFIX: ClassVar[str] = IpIdPrefix.WEBHOOK_ENDPOINT.value

    id: str
    tenant_id: str
    endpoint_slug: str
    name: str
    description: str = ""
    verification_strategy: VerificationStrategy = VerificationStrategy.SHARED_HEADER_SECRET
    primary_secret_hash: str
    secondary_secret_hash: str | None = None
    secret_rotated_at: str | None = None
    bound_connection_id: str | None = None
    is_active: bool = True
    event_routes: list[WebhookEventRoute] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        endpoint_slug: str,
        name: str,
        primary_secret_hash: str,
        description: str = "",
        verification_strategy: VerificationStrategy = VerificationStrategy.SHARED_HEADER_SECRET,
        bound_connection_id: str | None = None,
        endpoint_id: str | None = None,
    ) -> WebhookEndpoint:
        """Factory method to instantiate and record inception of a WebhookEndpoint."""
        now = datetime.now(UTC).isoformat()
        resolved_id = endpoint_id or generate_id(cls.ID_PREFIX)
        cleaned_slug = endpoint_slug.strip().lower()

        endpoint = cls(
            id=resolved_id,
            tenant_id=tenant_id.strip(),
            endpoint_slug=cleaned_slug,
            name=name.strip(),
            description=description.strip(),
            verification_strategy=verification_strategy,
            primary_secret_hash=primary_secret_hash,
            bound_connection_id=bound_connection_id,
            is_active=True,
            created_at=now,
            updated_at=now,
        )

        endpoint.add_domain_event(
            WebhookEndpointCreatedEvent(
                endpoint_id=resolved_id,
                tenant_id=tenant_id,
                endpoint_slug=cleaned_slug,
                name=name,
                verification_strategy=verification_strategy.value,
                bound_connection_id=bound_connection_id,
            )
        )
        return endpoint

    def match_route(self, event_name: str | None) -> WebhookEventRoute | None:
        """Evaluates active routes sorted by priority (lowest value = evaluated first).

        Returns the highest-priority route matching the discriminator, or None if unmapped.
        """
        sorted_routes = sorted(
            [r for r in self.event_routes if r.is_active],
            key=lambda r: r.priority,
        )
        for route in sorted_routes:
            if route.matches(event_name):
                return route
        return None

    def rotate_secret(self, new_secret_hash: str) -> None:
        """Rotates cryptographic secret, transitioning the old secret to secondary fallback."""
        now = datetime.now(UTC).isoformat()
        self.secondary_secret_hash = self.primary_secret_hash
        self.primary_secret_hash = new_secret_hash
        self.secret_rotated_at = now
        self.updated_at = now

        self.add_domain_event(
            WebhookSecretRotatedEvent(
                endpoint_id=self.id,
                tenant_id=self.tenant_id,
                endpoint_slug=self.endpoint_slug,
                secret_rotated_at=now,
            )
        )

    def deactivate(self) -> None:
        """Deactivates endpoint, rejecting subsequent inbound webhook traffic."""
        self.is_active = False
        self.updated_at = datetime.now(UTC).isoformat()

        self.add_domain_event(
            WebhookEndpointDeactivatedEvent(
                endpoint_id=self.id,
                tenant_id=self.tenant_id,
                endpoint_slug=self.endpoint_slug,
            )
        )

    def add_event_route(self, route: WebhookEventRoute) -> None:
        """Attaches a new multiplexed event route to the endpoint."""
        self.event_routes.append(route)
        self.updated_at = datetime.now(UTC).isoformat()

        self.add_domain_event(
            WebhookEventRouteAddedEvent(
                endpoint_id=self.id,
                tenant_id=self.tenant_id,
                route_id=route.id,
                event_pattern=route.event_pattern,
                payload_semantic=route.payload_semantic.value,
                target_pipeline_or_workflow_id=route.target_pipeline_or_workflow_id,
                priority=route.priority,
            )
        )

    def update_metadata(
        self,
        *,
        name: str,
        description: str,
        bound_connection_id: str | None = None,
    ) -> None:
        """Updates display metadata and connection binding."""
        self.name = name.strip()
        self.description = description.strip()
        self.bound_connection_id = bound_connection_id
        self.updated_at = datetime.now(UTC).isoformat()

        self.add_domain_event(
            WebhookEndpointUpdatedEvent(
                endpoint_id=self.id,
                tenant_id=self.tenant_id,
                endpoint_slug=self.endpoint_slug,
                name=self.name,
                bound_connection_id=bound_connection_id,
            )
        )
