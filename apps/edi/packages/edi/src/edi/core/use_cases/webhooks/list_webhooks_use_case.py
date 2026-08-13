from collections.abc import Sequence

from domain.models import WebhookDomainModel

from edi.ports.uow import ControlPlaneUnitOfWorkPort as ControlPlaneUnitOfWork


class ListWebhooksUseCase:
    def __init__(self, uow: ControlPlaneUnitOfWork) -> None:
        self.uow = uow

    async def execute(self, tenant_id: str) -> Sequence[WebhookDomainModel]:
        async with self.uow:
            return await self.uow.webhooks.list_webhooks(tenant_id)
