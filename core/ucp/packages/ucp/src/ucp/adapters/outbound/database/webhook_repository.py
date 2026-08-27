import os
from collections.abc import Sequence
from datetime import UTC, datetime

from database.models import Webhook as DbWebhook
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from ucp_models.events import ControlPlaneOutbox

from ucp.domain.models.webhook import WebhookDomainModel
from ucp.ports.outbound.webhook_repository_port import WebhookRepositoryPort


class SqlAlchemyWebhookRepository(WebhookRepositoryPort):
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _map_to_domain(self, row: DbWebhook) -> WebhookDomainModel:
        webhook = WebhookDomainModel(
            id=row.id,
            tenant_id=row.tenant_id,
            name=row.name,
            url=row.url,
            auth_header_vault_ref=row.auth_header_vault_ref,
            active=row.active,
            created_at=row.created_at.replace(tzinfo=UTC),
            updated_at=row.updated_at.replace(tzinfo=UTC),
        )
        return webhook

    async def list_webhooks(self, tenant_id: str) -> Sequence[WebhookDomainModel]:
        result = await self.session.execute(
            select(DbWebhook).where(
                DbWebhook.tenant_id == tenant_id, DbWebhook.deleted_at.is_(None)
            )
        )
        return [self._map_to_domain(r) for r in result.scalars().all()]

    async def get_webhooks_by_ids(self, tenant_id: str, ids: list[str]) -> dict[str, str]:
        if not ids:
            return {}
        result = await self.session.execute(
            select(DbWebhook.id, DbWebhook.name).where(
                DbWebhook.id.in_(ids),
                DbWebhook.tenant_id == tenant_id,
                DbWebhook.deleted_at.is_(None),
            )
        )
        return {row.id: row.name for row in result.all()}

    async def find_by_id(self, tenant_id: str, webhook_id: str) -> WebhookDomainModel | None:
        result = await self.session.execute(
            select(DbWebhook).where(
                DbWebhook.id == webhook_id,
                DbWebhook.tenant_id == tenant_id,
                DbWebhook.deleted_at.is_(None),
            )
        )
        record = result.scalars().first()
        if not record:
            return None
        return self._map_to_domain(record)

    async def save(self, webhook: WebhookDomainModel, idempotency_key: str | None = None) -> None:
        stmt = select(DbWebhook).where(
            DbWebhook.id == webhook.id,
            DbWebhook.tenant_id == webhook.tenant_id,
            DbWebhook.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        record = result.scalars().first()

        if record:
            record.name = webhook.name
            record.url = webhook.url
            record.active = webhook.active
            record.auth_header_vault_ref = webhook.auth_header_vault_ref
        else:
            record = DbWebhook(
                id=webhook.id,
                tenant_id=webhook.tenant_id,
                name=webhook.name,
                url=webhook.url,
                auth_header_vault_ref=webhook.auth_header_vault_ref,
                active=webhook.active,
                created_at=webhook.created_at.replace(tzinfo=None),
                updated_at=webhook.updated_at.replace(tzinfo=None),
            )
            self.session.add(record)

        self._flush_events(webhook, idempotency_key)

    def _flush_events(
        self, webhook: WebhookDomainModel, idempotency_key: str | None = None
    ) -> None:
        for index, event in enumerate(webhook.domain_events):
            outbox_id = f"{ControlPlaneOutbox.ID_PREFIX}_{os.urandom(12).hex()}"
            event_name = event.event_name

            final_idemp_key = (
                f"{idempotency_key}_{index}"
                if idempotency_key
                else getattr(event, "id", f"{event_name}_{webhook.id}_{index}")
            )

            outbox_event = ControlPlaneOutbox(
                id=outbox_id,
                idempotency_key=final_idemp_key,
                tenant_id=webhook.tenant_id,
                event_type=event_name,
                payload=event.to_dict() if hasattr(event, "to_dict") else {},
            )
            self.session.add(outbox_event)

        webhook.clear_domain_events()

    async def delete_webhook(
        self, webhook: WebhookDomainModel, deleted_by: str, idempotency_key: str | None = None
    ) -> None:
        # Flush domain events from the aggregate before soft-deleting
        self._flush_events(webhook, idempotency_key)
        await self.session.execute(
            update(DbWebhook)
            .where(DbWebhook.id == webhook.id, DbWebhook.tenant_id == webhook.tenant_id)
            .values(deleted_at=datetime.now(UTC), deleted_by=deleted_by)
        )
        await self.session.flush()
