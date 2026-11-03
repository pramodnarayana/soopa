from collections.abc import Sequence
from typing import Protocol

from edi.domain.routing.webhook import Webhook


class WebhookRepositoryPort(Protocol):
    """Read-only port for accessing UCP-replicated Webhook configurations."""

    async def get_webhook(self, tenant_id: str, webhook_id: str) -> Webhook | None:
        """Fetch an active Webhook configuration for the given tenant."""
        ...

    async def list_webhooks(self, tenant_id: str) -> Sequence[Webhook]:
        """List non-deleted Webhook configurations for the given tenant."""
        ...
