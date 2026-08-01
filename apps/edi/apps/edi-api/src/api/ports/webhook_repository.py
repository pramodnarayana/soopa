from collections.abc import Sequence
from typing import Protocol

from domain.models import WebhookDomainModel


class WebhookRepositoryPort(Protocol):
    async def list_webhooks(self, tenant_id: str) -> Sequence[WebhookDomainModel]: ...
    async def get_webhooks_by_ids(self, tenant_id: str, ids: list[str]) -> dict[str, str]: ...
