from dataclasses import dataclass
from typing import Literal

from ucp.core.exceptions import ResourceNotFoundError
from ucp.ports.uow import UcpUnitOfWorkPort


@dataclass
class ToggleTenantStatusCommand:
    tenant_id: str
    status: Literal["active", "inactive"]


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

            tenant.change_status(command.status)
            await self._uow.tenant_repo.save(tenant, idempotency_key)

            await self._uow.commit()
