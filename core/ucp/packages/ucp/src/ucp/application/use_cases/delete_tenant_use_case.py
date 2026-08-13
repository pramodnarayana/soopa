import logging

from ucp.core.exceptions import ResourceNotFoundError
from ucp.ports.uow import UcpUnitOfWorkPort

logger = logging.getLogger(__name__)


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
            user_ids = [u.id for u in tenant_users]

            # 2. Register Outbox Event to Delete Zitadel Organization
            if tenant.idp_tenant_id:
                self.uow.register_event(
                    event_type="TenantDeleted",
                    payload={"org_id": tenant.idp_tenant_id},
                    idempotency_key=idempotency_key,
                    tenant_id=tenant.id,
                )

            # 3. Delete tenant and all its strictly dependent infrastructure resources
            # (api_keys, shards, outbox events, and the tenant_users bridge records)
            await self.uow.tenant_repo.delete(tenant_id, idempotency_key)

            # 4. Delete any users that no longer belong to any active tenants
            if user_ids:
                await self.uow.user_repo.delete_orphaned_users(user_ids)

            await self.uow.commit()
