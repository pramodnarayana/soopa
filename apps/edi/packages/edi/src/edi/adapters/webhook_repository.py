from collections.abc import Sequence

from database.base_repository import GlobalSession, GlobalSqlAlchemyRepository
from domain.models import WebhookDomainModel
from platform_orm.models import (
    Webhook,
)
from sqlalchemy import select

from edi.ports.webhook_repository import WebhookRepositoryPort


class SqlAlchemyWebhookRepository(WebhookRepositoryPort, GlobalSqlAlchemyRepository):
    def __init__(self, session: GlobalSession) -> None:
        GlobalSqlAlchemyRepository.__init__(self, session)

    async def list_webhooks(self, tenant_id: str) -> Sequence[WebhookDomainModel]:
        result = await self.session.execute(select(Webhook).where(Webhook.tenant_id == tenant_id))
        return [WebhookDomainModel.model_validate(r) for r in result.scalars().all()]

    async def get_webhooks_by_ids(self, tenant_id: str, ids: list[str]) -> dict[str, str]:
        if not ids:
            return {}
        result = await self.session.execute(
            select(Webhook.id, Webhook.name).where(
                Webhook.id.in_(ids), Webhook.tenant_id == tenant_id
            )
        )
        return {row.id: row.name for row in result.all()}

    async def create_webhook(
        self, tenant_id: str, name: str, url: str, auth_header_vault_ref: str | None
    ) -> WebhookDomainModel:
        record = Webhook(
            tenant_id=tenant_id,
            name=name,
            url=url,
            auth_header_vault_ref=auth_header_vault_ref,
            active=True,
        )
        self.session.add(record)
        await self.session.flush()
        return WebhookDomainModel.model_validate(record)

    async def update_webhook(
        self,
        tenant_id: str,
        webhook_id: str,
        name: str | None,
        url: str | None,
        active: bool | None,
    ) -> WebhookDomainModel:
        result = await self.session.execute(
            select(Webhook).where(Webhook.id == webhook_id, Webhook.tenant_id == tenant_id)
        )
        record = result.scalars().first()
        if not record:
            raise ValueError(f"Webhook {webhook_id} not found")

        if name is not None:
            record.name = name
        if url is not None:
            record.url = url
        if active is not None:
            record.active = active

        await self.session.flush()
        return WebhookDomainModel.model_validate(record)

    async def delete_webhook(self, tenant_id: str, webhook_id: str) -> None:
        result = await self.session.execute(
            select(Webhook).where(Webhook.id == webhook_id, Webhook.tenant_id == tenant_id)
        )
        record = result.scalars().first()
        if not record:
            raise ValueError(f"Webhook {webhook_id} not found")

        await self.session.delete(record)
        await self.session.flush()
