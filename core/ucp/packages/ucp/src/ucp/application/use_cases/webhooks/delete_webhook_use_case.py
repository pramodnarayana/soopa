from __future__ import annotations

import structlog
from seedwork.domain.exceptions import Result

from ucp.domain.exceptions import UcpError, WebhookNotFoundError
from ucp.ports.outbound.uow_port import UcpUnitOfWorkPort

logger = structlog.get_logger(__name__)


class DeleteWebhookUseCase:
    def __init__(self, uow: UcpUnitOfWorkPort) -> None:
        self.uow = uow

    async def execute(
        self,
        tenant_id: str,
        webhook_id: str,
        deleted_by: str,
        idempotency_key: str | None = None,
    ) -> Result[None, UcpError]:
        bound_logger = logger.bind(tenant_id=tenant_id, webhook_id=webhook_id)
        bound_logger.info("ucp_webhook_deletion_started", idempotency_key=idempotency_key)

        async with self.uow:
            if idempotency_key:
                is_completed, _res_body, _res_status = await self.uow.idempotency_repo.get_result(
                    tenant_id, idempotency_key
                )
                if is_completed:
                    bound_logger.info("ucp_webhook_deletion_idempotent_result_returned")
                    return Result.ok(None)

            webhook = await self.uow.webhook_repo.find_by_id(tenant_id, webhook_id)
            if not webhook:
                bound_logger.error("ucp_webhook_deletion_not_found")
                return Result.fail(WebhookNotFoundError.for_id(webhook_id, tenant_id))

            del_res = webhook.mark_deleted()
            if del_res.is_err:
                err = del_res.unwrap_err()
                bound_logger.error(
                    "ucp_webhook_deletion_conflict",
                    code=err.code.value,
                    reason=err.message,
                )
                return Result.fail(err)

            if idempotency_key:
                await self.uow.idempotency_repo.save_result(
                    tenant_id=tenant_id,
                    idempotency_key=idempotency_key,
                    response_body={},
                    response_status_code=204,
                )

            bound_logger.debug(
                "ucp_webhook_deletion_flushing_events",
                domain_events_queued=len(webhook.domain_events),
            )
            await self.uow.webhook_repo.delete_webhook(
                webhook=webhook, deleted_by=deleted_by, idempotency_key=idempotency_key
            )
            await self.uow.commit()

        bound_logger.info("ucp_webhook_deleted")
        return Result.ok(None)
