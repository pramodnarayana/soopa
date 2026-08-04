from collections.abc import Sequence

from database.base_repository import GlobalSession, GlobalSqlAlchemyRepository
from domain.models import WebhookDomainModel
from sqlalchemy import select
from ucp_models.webhooks import (
    Webhook,
)

from api.ports.webhook_repository import WebhookRepositoryPort


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
