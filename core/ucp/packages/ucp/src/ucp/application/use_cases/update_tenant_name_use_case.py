from dataclasses import dataclass

from ucp.ports.uow import UcpUnitOfWorkPort


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
        async with self._uow:
            tenant = await self._uow.tenant_repo.find_by_id(command.tenant_id)
            if not tenant:
                tenant = await self._uow.tenant_repo.find_by_idp_tenant_id(command.tenant_id)

            if not tenant:
                raise ValueError("Tenant not found")

            tenant.rename(command.name)
            await self._uow.tenant_repo.save(tenant, idempotency_key)

            self._uow.register_event(
                event_type="TenantNameUpdated",
                payload={"org_id": tenant.idp_tenant_id, "name": command.name},
                idempotency_key=idempotency_key,
                tenant_id=tenant.id,
            )

            await self._uow.commit()
