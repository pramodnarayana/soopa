from ucp.domain.exceptions import ResourceNotFoundError
from ucp.ports.outbound.uow import UcpUnitOfWorkPort


class DeleteTenantUseCase:
    def __init__(
        self,
        uow: UcpUnitOfWorkPort,
    ):
        self.uow = uow

    async def execute(self, tenant_id: str, idempotency_key: str | None = None) -> None:
        async with self.uow:
            tenant = await self.uow.tenant_repo.find_by_id(tenant_id)
            if not tenant:
                raise ResourceNotFoundError("Tenant not found")

            # 1. Fetch users belonging to this tenant before deletion
            tenant_users = await self.uow.user_repo.find_users_by_tenant(tenant_id)

            # 2. Add domain event to delete Zitadel Organization
            tenant.mark_deleted()

            # 3. Delete tenant and all its strictly dependent infrastructure resources
            # (api_keys, shards, outbox events, and the tenant_users bridge records)
            await self.uow.tenant_repo.delete(tenant, idempotency_key)

            # 4. Delete any users that no longer belong to any active tenants
            for user in tenant_users:
                has_memberships = await self.uow.user_repo.has_any_tenant_memberships(user.id)
                if not has_memberships:
                    user.mark_deleted()
                    await self.uow.user_repo.delete(user)

            await self.uow.commit()
