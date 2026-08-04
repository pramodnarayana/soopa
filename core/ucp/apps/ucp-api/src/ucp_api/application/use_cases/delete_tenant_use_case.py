import logging
from typing import Optional
from ucp_api.core.exceptions import ResourceNotFoundError
from ucp_api.ports.outbound.tenant_repository import ITenantRepository
from ucp_api.ports.outbound.user_repository import IUserRepository
from ucp_api.ports.outbound.organization_provider import IOrganizationProvider

logger = logging.getLogger(__name__)

class DeleteTenantUseCase:
    def __init__(
        self,
        tenant_repo: ITenantRepository,
        user_repo: IUserRepository,
        organization_provider: IOrganizationProvider,
    ):
        self.tenant_repo = tenant_repo
        self.user_repo = user_repo
        self.organization_provider = organization_provider

    async def execute(self, tenant_id: str, idempotency_key: Optional[str] = None) -> None:
        tenant = await self.tenant_repo.find_by_id(tenant_id)
        if not tenant:
            raise ResourceNotFoundError("Tenant not found")

        # 1. Fetch users belonging to this tenant before deletion
        tenant_users = await self.user_repo.find_users_by_tenant(tenant_id)
        user_ids = [u.id for u in tenant_users]

        # 2. Delete tenant and all its strictly dependent infrastructure resources
        # (api_keys, shards, outbox events, and the tenant_users bridge records)
        await self.tenant_repo.delete(tenant_id, idempotency_key)

        # 3. Delete any users that no longer belong to any active tenants
        if user_ids:
            await self.user_repo.delete_orphaned_users(user_ids)

        # 4. Clean up Zitadel Organization (best effort)
        if tenant.idp_tenant_id:
            try:
                await self.organization_provider.delete_organization(tenant.idp_tenant_id)
            except Exception as err:
                logger.error(
                    f"Warning: Failed to delete organization {tenant.idp_tenant_id} from Zitadel: {err}"
                )
