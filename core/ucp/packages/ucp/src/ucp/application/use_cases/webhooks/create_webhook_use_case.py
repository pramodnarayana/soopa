from __future__ import annotations

import structlog
from seedwork.domain.exceptions import Result

from ucp.domain.exceptions import UcpError
from ucp.domain.webhook import Webhook
from ucp.ports.outbound.uow_port import UcpUnitOfWorkPort

logger = structlog.get_logger(__name__)


class CreateWebhookUseCase:
    def __init__(self, uow: UcpUnitOfWorkPort) -> None:
        self.uow = uow

    async def execute(
        self,
        tenant_id: str,
        name: str,
        url: str,
        auth_header_vault_ref: str | None,
        idempotency_key: str | None = None,
    ) -> Result[Webhook, UcpError]:
        bound_logger = logger.bind(tenant_id=tenant_id)
        bound_logger.info(
            "ucp_webhook_creation_started",
            webhook_name=name,
            idempotency_key=idempotency_key,
        )

        create_res = Webhook.create(
            tenant_id=tenant_id,
            name=name,
            url=url,
            auth_header_vault_ref=auth_header_vault_ref,
        )
        if create_res.is_err:
            err = create_res.unwrap_err()
            bound_logger.error(
                "ucp_webhook_creation_validation_failed",
                code=err.code.value,
                reason=err.message,
            )
            return create_res

        webhook = create_res.unwrap()

        async with self.uow:
            await self.uow.webhook_repo.save(webhook, idempotency_key=idempotency_key)
            await self.uow.commit()

        bound_logger.info("ucp_webhook_created", webhook_id=webhook.id)
        return Result.ok(webhook)
