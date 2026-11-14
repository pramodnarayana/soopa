"""Webhook endpoint repository port interface."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from ip.engine.domain.webhook.endpoint import WebhookEndpoint


class WebhookEndpointRepositoryPort(Protocol):
    """Protocol for persisting and retrieving WebhookEndpoint aggregates and routes."""

    async def get_by_id(self, endpoint_id: str) -> WebhookEndpoint | None:
        """Retrieves a WebhookEndpoint by its unique identifier."""
        ...

    async def get_by_slug(self, tenant_id: str, endpoint_slug: str) -> WebhookEndpoint | None:
        """Retrieves a WebhookEndpoint by tenant and endpoint slug with routes eager loaded."""
        ...

    async def save(self, endpoint: WebhookEndpoint) -> None:
        """Persists the WebhookEndpoint and its associated WebhookEventRoutes atomically."""
        ...

    async def list_by_tenant(self, tenant_id: str) -> Sequence[WebhookEndpoint]:
        """Lists all webhook endpoints for a given tenant."""
        ...

    async def delete(self, endpoint_id: str) -> None:
        """Deletes a WebhookEndpoint and cascades to its event routes."""
        ...
