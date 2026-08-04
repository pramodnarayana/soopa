from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from ucp_api.domain.models.tenant import Tenant

from identity.domain.identity_context import IdentityContext

from ucp_api.adapters.inbound.http.dtos.tenant_dtos import (
    ProvisionTenantRequest,
    TenantResponse,
    UpdateTenantNameRequest,
    UpdateTenantStatusRequest,
)
from ucp_api.adapters.inbound.http.guards.platform_auth_guard import require_platform_admin
from ucp_api.application.use_cases.delete_tenant_use_case import DeleteTenantUseCase
from ucp_api.application.use_cases.provision_tenant_use_case import (
    ProvisionTenantCommand,
    ProvisionTenantUseCase,
)
from ucp_api.core.config import get_settings
from ucp_api.ports.outbound.project_provider import IProjectProvider
from ucp_api.ports.outbound.tenant_repository import ITenantRepository

router = APIRouter(prefix="/tenants", tags=["Tenants"])


# Dependency placeholders — overridden in main.py via dependency_overrides
def get_tenant_repo() -> ITenantRepository:
    raise NotImplementedError()


def get_project_provider() -> IProjectProvider:
    raise NotImplementedError()


def get_provision_tenant_use_case() -> ProvisionTenantUseCase:
    raise NotImplementedError()


def get_delete_tenant_use_case() -> DeleteTenantUseCase:
    raise NotImplementedError()


@router.get("/", response_model=List[TenantResponse])
async def find_all(  # type: ignore
    _: Annotated[IdentityContext, Depends(require_platform_admin)],
    tenant_repo: ITenantRepository = Depends(get_tenant_repo),
):
    tenants = await tenant_repo.find_all()
    return [TenantResponse.from_domain(t) for t in tenants]


@router.get("/roles")
async def get_roles(  # type: ignore
    _: Annotated[IdentityContext, Depends(require_platform_admin)],
    project_provider: IProjectProvider = Depends(get_project_provider),
):
    roles = await project_provider.get_roles()
    tenant_group = get_settings().zitadel_tenant_role_group
    return [role for role in roles if role.group == tenant_group]


async def resolve_tenant(id: str, tenant_repo: ITenantRepository) -> "Tenant":
    tenant = await tenant_repo.find_by_id(id)
    if not tenant:
        tenant = await tenant_repo.find_by_idp_tenant_id(id)
    return tenant  # type: ignore


@router.get("/{id}", response_model=TenantResponse)
async def find_one(  # type: ignore
    id: str,
    _: Annotated[IdentityContext, Depends(require_platform_admin)],
    tenant_repo: ITenantRepository = Depends(get_tenant_repo),
):
    tenant = await resolve_tenant(id, tenant_repo)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return TenantResponse.from_domain(tenant)


@router.post("/", response_model=TenantResponse)
async def provision(  # type: ignore
    dto: ProvisionTenantRequest,
    _: Annotated[IdentityContext, Depends(require_platform_admin)],
    idempotency_key: Optional[str] = Header(None, alias="idempotency-key"),
    use_case: ProvisionTenantUseCase = Depends(get_provision_tenant_use_case),
):
    command = ProvisionTenantCommand(name=dto.name)
    tenant = await use_case.execute(command, idempotency_key)
    return TenantResponse.from_domain(tenant)


@router.patch("/{id}/name", response_model=TenantResponse)
async def update_name(  # type: ignore
    id: str,
    dto: UpdateTenantNameRequest,
    _: Annotated[IdentityContext, Depends(require_platform_admin)],
    idempotency_key: Optional[str] = Header(None, alias="idempotency-key"),
    tenant_repo: ITenantRepository = Depends(get_tenant_repo),
):
    tenant = await resolve_tenant(id, tenant_repo)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    tenant.rename(dto.name)
    await tenant_repo.save(tenant, idempotency_key)
    return TenantResponse.from_domain(tenant)


@router.patch("/{id}/status", response_model=TenantResponse)
async def update_status(  # type: ignore
    id: str,
    dto: UpdateTenantStatusRequest,
    _: Annotated[IdentityContext, Depends(require_platform_admin)],
    idempotency_key: Optional[str] = Header(None, alias="idempotency-key"),
    tenant_repo: ITenantRepository = Depends(get_tenant_repo),
):
    tenant = await resolve_tenant(id, tenant_repo)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    tenant.change_status(dto.status)  # type: ignore
    await tenant_repo.save(tenant, idempotency_key)
    return TenantResponse.from_domain(tenant)


@router.delete("/{id}")
async def delete(  # type: ignore
    id: str,
    _: Annotated[IdentityContext, Depends(require_platform_admin)],
    idempotency_key: Optional[str] = Header(None, alias="idempotency-key"),
    tenant_repo: ITenantRepository = Depends(get_tenant_repo),
    use_case: DeleteTenantUseCase = Depends(get_delete_tenant_use_case),
):
    tenant = await resolve_tenant(id, tenant_repo)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    await use_case.execute(tenant.id, idempotency_key)
    return {"success": True}
