from __future__ import annotations

from urllib.parse import urlparse

import structlog
from seedwork.domain.exceptions import Result
from seedwork.domain.types import UNSET

from ucp.domain.exceptions import UcpError, WebhookNotFoundError
from ucp.domain.webhook import Webhook
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
    ) -> Result[Webhook, UcpError]:
        bound_logger = logger.bind(tenant_id=tenant_id, webhook_id=webhook_id)
        bound_logger.info("ucp_webhook_update_started", idempotency_key=idempotency_key)

        async with self.uow:
            webhook = await self.uow.webhook_repo.find_by_id(tenant_id, webhook_id)
            if not webhook:
                bound_logger.error("ucp_webhook_update_not_found")
                return Result.fail(WebhookNotFoundError.for_id(webhook_id))

            update_res = webhook.update(
                name=name if name is not None else UNSET,
                url=url if url is not None else UNSET,
                active=active if active is not None else UNSET,
            )
            if update_res.is_err:
                err = update_res.unwrap_err()
                bound_logger.error(
                    "ucp_webhook_update_validation_failed",
                    code=err.code.value,
                    reason=err.message,
                )
                return update_res

            parsed_url = urlparse(url) if url else None
            bound_logger.debug(
                "ucp_webhook_aggregate_updated",
                new_name=name,
                new_url_scheme=parsed_url.scheme if parsed_url else None,
                new_url_netloc=parsed_url.netloc if parsed_url else None,
                new_active=active,
                domain_events_queued=len(webhook.domain_events),
            )

            await self.uow.webhook_repo.save(webhook, idempotency_key=idempotency_key)
            await self.uow.commit()

        bound_logger.info("ucp_webhook_updated")
        return Result.ok(webhook)
