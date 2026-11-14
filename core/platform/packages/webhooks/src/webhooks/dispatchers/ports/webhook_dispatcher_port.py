"""Outbound webhook dispatcher port protocol."""

from __future__ import annotations

from typing import Protocol

from webhooks.dispatchers.domain.models import WebhookDeliveryResult, WebhookDispatchCommand


class WebhookDispatcherPort(Protocol):
    """Protocol for delivering outbound webhooks to external HTTP endpoints."""

    async def dispatch(self, command: WebhookDispatchCommand) -> WebhookDeliveryResult:
        """Executes the outbound webhook dispatch with resilience, signing, and SSRF defenses."""
        ...
