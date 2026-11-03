from __future__ import annotations

from dataclasses import dataclass

import structlog
from seedwork.domain.exceptions import Result

from ucp.application.use_cases._tenant_helpers import resolve_tenant
from ucp.domain.constants import LifecycleStatus
from ucp.domain.exceptions import UcpError
from ucp.ports.outbound.uow_port import UcpUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, kw_only=True)
class ToggleTenantStatusCommand:
    tenant_id: str
    is_active: bool


class ToggleTenantStatusUseCase:
    def __init__(self, uow: UcpUnitOfWorkPort) -> None:
        self._uow = uow

    async def execute(
        self, command: ToggleTenantStatusCommand, idempotency_key: str | None = None
    ) -> Result[None, UcpError]:
        bound_logger = logger.bind(tenant_id=command.tenant_id, is_active=command.is_active)
        bound_logger.info("toggle_tenant_status.started", idempotency_key=idempotency_key)

        async with self._uow:
            tenant_res = await resolve_tenant(self._uow, command.tenant_id)
            if tenant_res.is_err:
                bound_logger.error("toggle_tenant_status.tenant_not_found")
                return Result.fail(tenant_res.unwrap_err())

            tenant = tenant_res.unwrap()
            status = LifecycleStatus.ACTIVE if command.is_active else LifecycleStatus.INACTIVE
            status_res = tenant.change_status(status)
            if status_res.is_err:
                err = status_res.unwrap_err()
                bound_logger.error(
                    "toggle_tenant_status.failed",
                    code=err.code.value,
                    reason=err.message,
                )
                return Result.fail(err)

            await self._uow.tenant_repo.save(tenant, idempotency_key)
            await self._uow.commit()

        bound_logger.info("toggle_tenant_status.completed", resolved_tenant_id=tenant.id)
        return Result.ok(None)
