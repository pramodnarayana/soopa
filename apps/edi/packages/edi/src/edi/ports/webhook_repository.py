from collections.abc import Sequence
from typing import Protocol

from domain.models import WebhookDomainModel


class WebhookRepositoryPort(Protocol):
    async def list_webhooks(self, tenant_id: str) -> Sequence[WebhookDomainModel]: ...
    async def get_webhooks_by_ids(self, tenant_id: str, ids: list[str]) -> dict[str, str]: ...
    async def create_webhook(
        self, tenant_id: str, name: str, url: str, auth_header_vault_ref: str | None
    ) -> WebhookDomainModel: ...
    async def update_webhook(
        self,
        tenant_id: str,
        webhook_id: str,
        name: str | None,
        url: str | None,
        active: bool | None,
    ) -> WebhookDomainModel: ...
    async def delete_webhook(self, tenant_id: str, webhook_id: str) -> None: ...
