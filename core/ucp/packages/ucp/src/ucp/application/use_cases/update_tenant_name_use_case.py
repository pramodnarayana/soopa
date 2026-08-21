from dataclasses import dataclass

import structlog

from ucp.domain.exceptions import ResourceNotFoundError
from ucp.ports.outbound.uow import UcpUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass
class UpdateTenantNameCommand:
    tenant_id: str
    name: str


class UpdateTenantNameUseCase:
    def __init__(self, uow: UcpUnitOfWorkPort):
        self._uow = uow

    async def execute(
        self, command: UpdateTenantNameCommand, idempotency_key: str | None = None
    ) -> None:
        logger.info(
            "update_tenant_name.started",
            tenant_id=command.tenant_id,
            name=command.name,
            idempotency_key=idempotency_key,
        )
        async with self._uow:
            tenant = await self._uow.tenant_repo.find_by_id(command.tenant_id)
            if not tenant:
                tenant = await self._uow.tenant_repo.find_by_idp_tenant_id(command.tenant_id)

            if not tenant:
                logger.error("update_tenant_name.tenant_not_found", tenant_id=command.tenant_id)
                raise ResourceNotFoundError(f"Tenant {command.tenant_id} not found")

            tenant.rename(command.name)
            await self._uow.tenant_repo.save(tenant, idempotency_key)

            await self._uow.commit()

        logger.info(
            "update_tenant_name.completed",
            tenant_id=tenant.id,
            name=command.name,
        )
