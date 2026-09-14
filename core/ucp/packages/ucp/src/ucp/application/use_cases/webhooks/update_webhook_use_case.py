from urllib.parse import urlparse

import structlog

from ucp.domain.exceptions import ResourceNotFoundError
from ucp.domain.models.webhook import WebhookDomainModel
from ucp.ports.outbound.uow_port import UcpUnitOfWorkPort

logger = structlog.get_logger(__name__)


class UpdateWebhookUseCase:
    def __init__(self, uow: UcpUnitOfWorkPort) -> None:
        self.uow = uow

    async def execute(
        self,
        tenant_id: str,
        webhook_id: str,
        name: str | None,
        url: str | None,
        active: bool | None,
        idempotency_key: str | None = None,
    ) -> WebhookDomainModel:
        bound_logger = logger.bind(tenant_id=tenant_id, webhook_id=webhook_id)
        bound_logger.info("ucp_webhook_update_started", idempotency_key=idempotency_key)

        async with self.uow:
            webhook = await self.uow.webhook_repo.find_by_id(tenant_id, webhook_id)
            if not webhook:
                bound_logger.error("ucp_webhook_update_not_found")
                raise ResourceNotFoundError(f"Webhook {webhook_id} not found")

            webhook.update(name=name, url=url, active=active)

            _parsed_url = urlparse(url) if url else None
            bound_logger.debug(
                "ucp_webhook_aggregate_updated",
                new_name=name,
                new_url_scheme=_parsed_url.scheme if _parsed_url else None,
                new_url_netloc=_parsed_url.netloc if _parsed_url else None,
                new_active=active,
                domain_events_queued=len(webhook.domain_events),
            )

            await self.uow.webhook_repo.save(webhook, idempotency_key=idempotency_key)
            await self.uow.commit()

            bound_logger.info("ucp_webhook_updated")
            return webhook
