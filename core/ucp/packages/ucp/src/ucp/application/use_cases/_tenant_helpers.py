from __future__ import annotations

from seedwork.domain.exceptions import Result

from ucp.domain.exceptions import TenantNotFoundError, UcpError
from ucp.domain.tenant import Tenant
from ucp.ports.outbound.uow_port import UcpUnitOfWorkPort


async def resolve_tenant(uow: UcpUnitOfWorkPort, tenant_id: str) -> Result[Tenant, UcpError]:
    tenant = await uow.tenant_repo.find_by_id(tenant_id)
    if not tenant:
        tenant = await uow.tenant_repo.find_by_idp_tenant_id(tenant_id)
    if not tenant:
        return Result.fail(TenantNotFoundError.for_id(tenant_id))
    return Result.ok(tenant)
