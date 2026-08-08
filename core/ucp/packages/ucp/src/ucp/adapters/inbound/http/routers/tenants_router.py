from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from identity.domain.identity_context import IdentityContext
from pydantic import BaseModel

from ucp.adapters.inbound.http.dtos.tenant_dtos import (
    ProvisionTenantRequest,
    TenantResponse,
    UpdateTenantNameRequest,
    UpdateTenantStatusRequest,
)
from ucp.adapters.inbound.http.guards.platform_auth_guard import require_platform_admin
from ucp.adapters.inbound.http.guards.tenant_auth_guard import require_tenant_member
from ucp.application.use_cases.delete_tenant_use_case import DeleteTenantUseCase
from ucp.application.use_cases.provision_tenant_use_case import (
    ProvisionTenantCommand,
    ProvisionTenantUseCase,
)
from ucp.core.config import get_settings
from ucp.domain.models.tenant import Tenant
from ucp.ports.outbound.project_provider import IProjectProvider
from ucp.ports.outbound.tenant_query_service import ITenantQueryService
from ucp.ports.outbound.tenant_repository import ITenantRepository

router = APIRouter(prefix="/tenants", tags=["Tenants"])


# Dependency placeholders — overridden in main.py via dependency_overrides
def get_tenant_repo() -> ITenantRepository:
    raise NotImplementedError()


def get_tenant_query_service() -> ITenantQueryService:
    raise NotImplementedError()


def get_project_provider() -> IProjectProvider:
    raise NotImplementedError()


def get_provision_tenant_use_case() -> ProvisionTenantUseCase:
    raise NotImplementedError()


def get_delete_tenant_use_case() -> DeleteTenantUseCase:
    raise NotImplementedError()


@router.get("", response_model=list[TenantResponse])
async def find_all(  # type: ignore
    _: Annotated[IdentityContext, Depends(require_platform_admin)],
    query_service: ITenantQueryService = Depends(get_tenant_query_service),
):
    tenants = await query_service.get_all_tenants()
    return [TenantResponse.from_read_model(t) for t in tenants]


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


@router.get("/{tenant_id}", response_model=TenantResponse)
async def find_one(  # type: ignore
    tenant_id: str,
    _: Annotated[IdentityContext, Depends(require_tenant_member)],
    query_service: ITenantQueryService = Depends(get_tenant_query_service),
):
    tenant_rm = await query_service.get_tenant_by_id(tenant_id)
    if not tenant_rm:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return TenantResponse.from_read_model(tenant_rm)


@router.post("", response_model=TenantResponse)
async def provision(  # type: ignore
    dto: ProvisionTenantRequest,
    _: Annotated[IdentityContext, Depends(require_platform_admin)],
    idempotency_key: str | None = Header(None, alias="idempotency-key"),
    use_case: ProvisionTenantUseCase = Depends(get_provision_tenant_use_case),
    query_service: ITenantQueryService = Depends(get_tenant_query_service),
):
    command = ProvisionTenantCommand(name=dto.name)
    tenant = await use_case.execute(command, idempotency_key)

    tenant_rm = await query_service.get_tenant_by_id(tenant.id)
    assert tenant_rm is not None
    return TenantResponse.from_read_model(tenant_rm)


@router.patch("/{id}/name", response_model=TenantResponse)
async def update_name(  # type: ignore
    id: str,
    dto: UpdateTenantNameRequest,
    _: Annotated[IdentityContext, Depends(require_platform_admin)],
    idempotency_key: str | None = Header(None, alias="idempotency-key"),
    tenant_repo: ITenantRepository = Depends(get_tenant_repo),
    query_service: ITenantQueryService = Depends(get_tenant_query_service),
):
    tenant = await resolve_tenant(id, tenant_repo)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    tenant.rename(dto.name)
    await tenant_repo.save(tenant, idempotency_key)

    tenant_rm = await query_service.get_tenant_by_id(tenant.id)
    assert tenant_rm is not None
    return TenantResponse.from_read_model(tenant_rm)


@router.patch("/{id}/status", response_model=TenantResponse)
async def update_status(  # type: ignore
    id: str,
    dto: UpdateTenantStatusRequest,
    _: Annotated[IdentityContext, Depends(require_platform_admin)],
    idempotency_key: str | None = Header(None, alias="idempotency-key"),
    tenant_repo: ITenantRepository = Depends(get_tenant_repo),
    query_service: ITenantQueryService = Depends(get_tenant_query_service),
):
    tenant = await resolve_tenant(id, tenant_repo)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    tenant.change_status(dto.status)  # type: ignore
    await tenant_repo.save(tenant, idempotency_key)

    tenant_rm = await query_service.get_tenant_by_id(tenant.id)
    assert tenant_rm is not None
    return TenantResponse.from_read_model(tenant_rm)


@router.delete("/{id}")
async def delete(  # type: ignore
    id: str,
    _: Annotated[IdentityContext, Depends(require_platform_admin)],
    idempotency_key: str | None = Header(None, alias="idempotency-key"),
    tenant_repo: ITenantRepository = Depends(get_tenant_repo),
    use_case: DeleteTenantUseCase = Depends(get_delete_tenant_use_case),
):
    tenant = await resolve_tenant(id, tenant_repo)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    await use_case.execute(tenant.id, idempotency_key)
    return {"success": True}


class SubscribeAppRequest(BaseModel):
    appId: str


class SubscriptionResponse(BaseModel):
    id: str
    appId: str
    tenantId: str
    status: str


@router.get("/{id}/subscriptions", response_model=list[SubscriptionResponse])
async def get_subscriptions(
    id: str,
    _: Annotated[IdentityContext, Depends(require_platform_admin)],
    tenant_repo: ITenantRepository = Depends(get_tenant_repo),
) -> list[SubscriptionResponse]:
    tenant = await resolve_tenant(id, tenant_repo)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    return [
        SubscriptionResponse(
            id=f"{tenant.id}_{sub.app_id}", appId=sub.app_id, tenantId=tenant.id, status=sub.status
        )
        for sub in tenant.subscriptions
    ]


@router.post("/{id}/subscriptions", response_model=SubscriptionResponse)
async def subscribe_app(
    id: str,
    dto: SubscribeAppRequest,
    _: Annotated[IdentityContext, Depends(require_platform_admin)],
    idempotency_key: str | None = Header(None, alias="idempotency-key"),
    tenant_repo: ITenantRepository = Depends(get_tenant_repo),
) -> SubscriptionResponse:
    tenant = await resolve_tenant(id, tenant_repo)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    try:
        tenant.subscribe(dto.appId)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(e))

    await tenant_repo.save(tenant, idempotency_key)
    return SubscriptionResponse(
        id=f"{tenant.id}_{dto.appId}", appId=dto.appId, tenantId=tenant.id, status="active"
    )


@router.delete("/{id}/subscriptions/{app_id}")
async def unsubscribe_app(
    id: str,
    app_id: str,
    _: Annotated[IdentityContext, Depends(require_platform_admin)],
    idempotency_key: str | None = Header(None, alias="idempotency-key"),
    tenant_repo: ITenantRepository = Depends(get_tenant_repo),
) -> dict[str, bool]:
    tenant = await resolve_tenant(id, tenant_repo)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    try:
        tenant.unsubscribe_from_app(app_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(e))

    await tenant_repo.save(tenant, idempotency_key)
    return {"success": True}
