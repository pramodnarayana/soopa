from collections.abc import Sequence

from sqlalchemy import select

from edi.adapters.outbound.database.base_repository import GlobalSession, GlobalSqlAlchemyRepository
from edi.adapters.outbound.database.models.data_plane import Webhook
from edi.domain.models.webhooks import WebhookDomainModel
from edi.ports.outbound.webhook_repository import WebhookRepositoryPort


class SqlAlchemyWebhookRepository(WebhookRepositoryPort, GlobalSqlAlchemyRepository):
    def __init__(self, session: GlobalSession) -> None:
        GlobalSqlAlchemyRepository.__init__(self, session)

    async def get_webhook(self, tenant_id: str, webhook_id: str) -> WebhookDomainModel | None:
        stmt = select(Webhook).where(
            Webhook.tenant_id == tenant_id, Webhook.id == webhook_id, Webhook.active.is_(True)
        )
        result = await self.session.execute(stmt)
        record = result.scalar_one_or_none()
        if not record:
            return None
        return WebhookDomainModel(
            id=str(record.id),
            tenant_id=str(record.tenant_id),
            url=str(record.url),
            name=str(record.name),
            active=bool(record.active),
            auth_header_vault_ref=record.auth_header_vault_ref,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    async def list_webhooks(self, tenant_id: str) -> Sequence[WebhookDomainModel]:
        return []

    async def save(self, aggregate: WebhookDomainModel) -> None: ...
    async def delete(self, aggregate: WebhookDomainModel) -> None: ...
