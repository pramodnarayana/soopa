from __future__ import annotations

from dataclasses import dataclass

import structlog
from seedwork.domain.exceptions import Result

from ucp.application.use_cases._tenant_helpers import resolve_tenant
from ucp.domain.exceptions import AppNotFoundError, UcpError
from ucp.ports.outbound.uow_port import UcpUnitOfWorkPort


@dataclass(frozen=True, kw_only=True)
class UnsubscribeAppCommand:
    tenant_id: str
    app_id: str


logger = structlog.get_logger(__name__)


class UnsubscribeAppUseCase:
    def __init__(self, uow: UcpUnitOfWorkPort) -> None:
        self.uow = uow

    async def execute(
        self, command: UnsubscribeAppCommand, idempotency_key: str | None = None
    ) -> Result[None, UcpError]:
        bound_logger = logger.bind(tenant_id=command.tenant_id, app_id=command.app_id)
        bound_logger.info("unsubscribe_app.started", idempotency_key=idempotency_key)

        async with self.uow as uow:
            tenant_res = await resolve_tenant(uow, command.tenant_id)
            if tenant_res.is_err:
                bound_logger.error("unsubscribe_app.tenant_not_found")
                return Result.fail(tenant_res.unwrap_err())

            tenant = tenant_res.unwrap()
            app = await uow.app_repo.find_by_id(command.app_id)
            if not app:
                bound_logger.error("unsubscribe_app.app_not_found")
                return Result.fail(AppNotFoundError.for_id(command.app_id))

            unsub_res = tenant.unsubscribe_from_app(command.app_id, app.idp_project_id)
            if unsub_res.is_err:
                err = unsub_res.unwrap_err()
                bound_logger.error(
                    "unsubscribe_app.domain_rejected",
                    code=err.code.value,
                    reason=err.message,
                )
                return Result.fail(err)

            await uow.tenant_repo.save(tenant, idempotency_key)
            await uow.commit()

        logger.info(
            "tenant_unsubscribed_from_app",
            tenant_id=tenant.id,
            app_id=command.app_id,
        )
        return Result.ok(None)
