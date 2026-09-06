from dataclasses import dataclass

from ucp.domain.constants import LifecycleStatus
from ucp.domain.exceptions import ResourceNotFoundError
from ucp.ports.outbound.uow_port import UcpUnitOfWorkPort


@dataclass(frozen=True, kw_only=True)
class ToggleTenantStatusCommand:
    tenant_id: str
    is_active: bool


class ToggleTenantStatusUseCase:
    def __init__(self, uow: UcpUnitOfWorkPort):
        self._uow = uow

    async def execute(
        self, command: ToggleTenantStatusCommand, idempotency_key: str | None = None
    ) -> None:
        async with self._uow:
            tenant = await self._uow.tenant_repo.find_by_id(command.tenant_id)
            if not tenant:
                tenant = await self._uow.tenant_repo.find_by_idp_tenant_id(command.tenant_id)

            if not tenant:
                raise ResourceNotFoundError("Tenant not found")

            status = LifecycleStatus.ACTIVE if command.is_active else LifecycleStatus.INACTIVE
            tenant.change_status(status)
            await self._uow.tenant_repo.save(tenant, idempotency_key)

            await self._uow.commit()
