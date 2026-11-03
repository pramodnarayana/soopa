from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from edi.adapters.outbound.database.models.data_plane import Webhook as OrmWebhook
from edi.domain.routing.webhook import Webhook
from edi.ports.outbound.webhook_repository import WebhookRepositoryPort


class SqlAlchemyDataPlaneWebhookRepository(WebhookRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_webhook(self, tenant_id: str, webhook_id: str) -> Webhook | None:
        stmt = select(OrmWebhook).where(
            OrmWebhook.tenant_id == tenant_id,
            OrmWebhook.id == webhook_id,
        )
        record = (await self.session.execute(stmt)).scalars().first()
        return self._to_domain_model(record) if record else None

    async def get_webhooks_by_tenant(
        self, tenant_id: str, limit: int = 100, offset: int = 0
    ) -> Sequence[Webhook]:
        stmt = (
            select(OrmWebhook).where(OrmWebhook.tenant_id == tenant_id).limit(limit).offset(offset)
        )
        records = (await self.session.execute(stmt)).scalars().all()
        return [self._to_domain_model(r) for r in records]

    async def list_webhooks(self, tenant_id: str) -> Sequence[Webhook]:
        return await self.get_webhooks_by_tenant(tenant_id)

    @staticmethod
    def _to_domain_model(record: OrmWebhook) -> Webhook:
        return Webhook(
            id=record.id,
            tenant_id=record.tenant_id,
            name=record.name,
            url=record.url,
            active=record.active,
            created_at=record.created_at,
            updated_at=record.updated_at,
            auth_header_vault_ref=record.auth_header_vault_ref,
        )
