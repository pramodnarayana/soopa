from collections.abc import Sequence

from sqlalchemy import select

from database.models.webhooks import Webhook as OrmWebhook
from edi.adapters.outbound.database.base_repository import (
    GlobalSession,
    GlobalSqlAlchemyRepository,
)
from edi.domain.routing.webhook import Webhook
from edi.ports.outbound.webhook_repository import WebhookRepositoryPort


class SqlAlchemyWebhookRepository(WebhookRepositoryPort, GlobalSqlAlchemyRepository):
    def __init__(self, session: GlobalSession) -> None:
        GlobalSqlAlchemyRepository.__init__(self, session)

    async def get_webhook(self, tenant_id: str, webhook_id: str) -> Webhook | None:
        stmt = select(OrmWebhook).where(
            OrmWebhook.tenant_id == tenant_id,
            OrmWebhook.id == webhook_id,
            OrmWebhook.active.is_(True),
            OrmWebhook.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        record = result.scalar_one_or_none()
        if not record:
            return None
        return self._to_domain_model(record)

    async def list_webhooks(self, tenant_id: str) -> Sequence[Webhook]:
        stmt = (
            select(OrmWebhook)
            .where(
                OrmWebhook.tenant_id == tenant_id,
                OrmWebhook.deleted_at.is_(None),
            )
            .order_by(OrmWebhook.created_at.asc())
        )
        records = (await self.session.execute(stmt)).scalars().all()
        return [self._to_domain_model(record) for record in records]

    @staticmethod
    def _to_domain_model(record: OrmWebhook) -> Webhook:
        return Webhook(
            id=str(record.id),
            tenant_id=str(record.tenant_id),
            url=str(record.url),
            name=str(record.name),
            active=bool(record.active),
            auth_header_vault_ref=record.auth_header_vault_ref,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )
