import os
from dataclasses import dataclass

from ucp.domain.models.tenant import Tenant
from ucp.ports.uow import UcpUnitOfWorkPort


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
        uow: UcpUnitOfWorkPort,
    ):
        self.uow = uow

    async def execute(
        self, command: ProvisionTenantCommand, idempotency_key: str | None = None
    ) -> Tenant:
        async with self.uow:
            # 1. Generate a local ID for the tenant
            local_id = f"{Tenant.ID_PREFIX}_{os.urandom(12).hex()}"

            # 2. Create Tenant Domain Entity (idp_tenant_id is None until outbox worker provisions it)
            tenant = Tenant.create(
                id=local_id,
                name=command.name,
                idp_tenant_id=None,
                subscriptions=[],
            )

            # 3. Save to DB
            await self.uow.tenant_repo.save(tenant, idempotency_key)

            # 4. Register Outbox Event to Provision in Zitadel
            self.uow.register_event(
                event_type="TenantProvisioned",
                payload={"name": command.name},
                idempotency_key=idempotency_key,
                tenant_id=tenant.id,
            )

            await self.uow.commit()

            return tenant
