from __future__ import annotations

from dataclasses import dataclass

import structlog
from seedwork.domain.exceptions import Result

from ucp.application.use_cases._tenant_helpers import resolve_tenant
from ucp.domain.exceptions import UcpError
from ucp.ports.outbound.uow_port import UcpUnitOfWorkPort


@dataclass(frozen=True, kw_only=True)
class UpdateTenantNameCommand:
    tenant_id: str
    name: str


logger = structlog.get_logger(__name__)


class UpdateTenantNameUseCase:
    def __init__(self, uow: UcpUnitOfWorkPort) -> None:
        self._uow = uow

    async def execute(
        self, command: UpdateTenantNameCommand, idempotency_key: str | None = None
    ) -> Result[None, UcpError]:
        logger.info(
            "update_tenant_name.started",
            tenant_id=command.tenant_id,
            name=command.name,
            idempotency_key=idempotency_key,
        )
        async with self._uow:
            tenant_res = await resolve_tenant(self._uow, command.tenant_id)
            if tenant_res.is_err:
                logger.error("update_tenant_name.tenant_not_found", tenant_id=command.tenant_id)
                return Result.fail(tenant_res.unwrap_err())

            tenant = tenant_res.unwrap()
            rename_res = tenant.rename(command.name)
            if rename_res.is_err:
                err = rename_res.unwrap_err()
                logger.error(
                    "update_tenant_name.validation_failed",
                    tenant_id=tenant.id,
                    code=err.code.value,
                    reason=err.message,
                )
                return Result.fail(err)

            await self._uow.tenant_repo.save(tenant, idempotency_key)
            await self._uow.commit()

        logger.info(
            "update_tenant_name.completed",
            tenant_id=tenant.id,
            name=tenant.name,
        )
        return Result.ok(None)
