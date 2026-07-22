from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from api.domain.models import (
    CreateWebhookCmd,
)
from domain.models import WebhookDomainModel


class WebhookRepositoryPort(Protocol):
    async def create_webhook(self, tenant_id: int, cmd: CreateWebhookCmd) -> UUID: ...
    async def get_webhook(self, tenant_id: int, webhook_id: UUID) -> WebhookDomainModel | None: ...
    async def update_webhook(
        self,
        tenant_id: int,
        webhook_id: UUID,
        name: str | None = None,
        active: bool | None = None,
        url: str | None = None,
    ) -> bool: ...
    async def delete_webhook(self, tenant_id: int, webhook_id: UUID) -> bool: ...
    async def list_webhooks(self, tenant_id: int) -> Sequence[WebhookDomainModel]: ...
    async def get_webhooks_by_ids(self, tenant_id: int, ids: list[UUID]) -> dict[UUID, str]: ...
