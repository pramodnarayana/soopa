import uuid
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from database.base_repository import GlobalSession, GlobalSqlAlchemyRepository
from database.models.control_plane import (
    Webhook,
)
from domain.models import WebhookDomainModel
from sqlalchemy import delete, select, update

from api.domain.models import (
    CreateWebhookCmd,
)
from api.ports.webhook_repository import WebhookRepositoryPort


class SqlAlchemyWebhookRepository(WebhookRepositoryPort, GlobalSqlAlchemyRepository):
    def __init__(self, session: GlobalSession) -> None:
        GlobalSqlAlchemyRepository.__init__(self, session)

    # ------------------------------------------------------------------------
    # Webhook Partners (Now in Control Plane)
    # ------------------------------------------------------------------------
    async def create_webhook(self, tenant_id: str, cmd: CreateWebhookCmd) -> UUID:
        partner_id = uuid.uuid4()
        record = Webhook(
            id=partner_id,
            tenant_id=tenant_id,
            name=cmd.name,
            url=cmd.url,
            auth_header_vault_ref=cmd.auth_header_vault_ref,
            active=False,
        )
        self.session.add(record)
        await self.session.flush()
        return partner_id

    async def get_webhook(self, tenant_id: str, partner_id: UUID) -> WebhookDomainModel | None:
        result = await self.session.execute(
            select(Webhook).where(Webhook.id == partner_id, Webhook.tenant_id == tenant_id)
        )
        record = result.scalar_one_or_none()
        return WebhookDomainModel.model_validate(record) if record else None

    async def update_webhook(
        self,
        tenant_id: str,
        webhook_id: UUID,
        name: str | None = None,
        active: bool | None = None,
        url: str | None = None,
    ) -> bool:
        values: dict[str, Any] = {}
        if name is not None:
            values["name"] = name
        if active is not None:
            values["active"] = active
        if url is not None:
            values["url"] = url

        if not values:
            return True

        stmt = (
            update(Webhook)
            .where(Webhook.id == webhook_id, Webhook.tenant_id == tenant_id)
            .values(**values)
        )
        result = await self.session.execute(stmt)
        return (getattr(result, "rowcount", 0) or 0) > 0

    async def delete_webhook(self, tenant_id: str, webhook_id: UUID) -> bool:
        stmt = delete(Webhook).where(Webhook.id == webhook_id, Webhook.tenant_id == tenant_id)
        result = await self.session.execute(stmt)
        return (getattr(result, "rowcount", 0) or 0) > 0

    async def list_webhooks(self, tenant_id: str) -> Sequence[WebhookDomainModel]:
        result = await self.session.execute(select(Webhook).where(Webhook.tenant_id == tenant_id))
        return [WebhookDomainModel.model_validate(r) for r in result.scalars().all()]

    async def get_webhooks_by_ids(self, tenant_id: str, ids: list[UUID]) -> dict[UUID, str]:
        if not ids:
            return {}
        result = await self.session.execute(
            select(Webhook.id, Webhook.name).where(
                Webhook.id.in_(ids), Webhook.tenant_id == tenant_id
            )
        )
        return {row.id: row.name for row in result.all()}
