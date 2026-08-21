from ucp.domain.exceptions import ResourceNotFoundError
from ucp.domain.models.tenant import Tenant
from ucp.ports.outbound.uow_port import UcpUnitOfWorkPort


async def resolve_tenant_or_raise(uow: UcpUnitOfWorkPort, tenant_id: str) -> Tenant:
    tenant = await uow.tenant_repo.find_by_id(tenant_id)
    if not tenant:
        tenant = await uow.tenant_repo.find_by_idp_tenant_id(tenant_id)
    if not tenant:
        raise ResourceNotFoundError(f"Tenant '{tenant_id}' not found.")
    return tenant
