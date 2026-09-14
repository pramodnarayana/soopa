from collections.abc import Sequence
from typing import Protocol

from edi.domain.models.webhooks import WebhookDomainModel


class WebhookRepositoryPort(Protocol):
    """
    Port for accessing Webhook configurations.
    """

    async def get_webhook(self, tenant_id: str, webhook_id: str) -> WebhookDomainModel | None:
        """
        Fetches Webhook partner config and returns a typed DTO.
        """
        ...

    async def list_webhooks(self, tenant_id: str) -> Sequence[WebhookDomainModel]: ...
    async def save(self, aggregate: WebhookDomainModel) -> None: ...
    async def delete(self, aggregate: WebhookDomainModel) -> None: ...
