import os
from dataclasses import dataclass

from ucp.domain.models.tenant import Tenant
from ucp.ports.outbound.organization_provider import IOrganizationProvider
from ucp.ports.outbound.tenant_repository import ITenantRepository
from ucp.ports.outbound.user_identity_provider import IUserIdentityProvider


@dataclass(frozen=True)
class ProvisionTenantCommand:
    """
    Immutable command object carrying the intent to provision a new tenant.

    This is a pure application-layer concept with no dependency on HTTP or
    serialisation frameworks. Routers map their HTTP DTOs into this command
    before invoking the use case.
    """

    name: str


class ProvisionTenantUseCase:
    def __init__(
        self,
        tenant_repo: ITenantRepository,
        organization_provider: IOrganizationProvider,
        user_identity_provider: IUserIdentityProvider,
    ):
        self.tenant_repo = tenant_repo
        self.organization_provider = organization_provider
        self.user_identity_provider = user_identity_provider

    async def execute(
        self, command: ProvisionTenantCommand, idempotency_key: str | None = None
    ) -> Tenant:
        # 1. Call Zitadel to create an Organization
        org_id, _ = await self.organization_provider.create_organization(command.name)

        # 2. Generate a local ID for the tenant
        local_id = f"{Tenant.ID_PREFIX}_{os.urandom(12).hex()}"

        # 3. Create Tenant Domain Entity (mapping Zitadel orgId to our generic idp_tenant_id)
        tenant = Tenant.create(
            id=local_id,
            name=command.name,
            idp_tenant_id=org_id,
            subscriptions=[],
        )

        # 4. Save to DB (Repository handles Transaction and Outbox automatically)
        await self.tenant_repo.save(tenant, idempotency_key)

        return tenant
