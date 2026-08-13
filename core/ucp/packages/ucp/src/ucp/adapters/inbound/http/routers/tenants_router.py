from typing import Annotated, Any

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Header, HTTPException
from identity.domain.identity_context import IdentityContext
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

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
from ucp.application.use_cases.toggle_tenant_status_use_case import (
    ToggleTenantStatusCommand,
    ToggleTenantStatusUseCase,
)
from ucp.application.use_cases.update_tenant_name_use_case import (
    UpdateTenantNameCommand,
    UpdateTenantNameUseCase,
)
from ucp.bootstrap.container import Container
from ucp.core.config import get_settings
from ucp.core.container import get_db_session
from ucp.domain.models.tenant import Tenant
from ucp.ports.outbound.project_provider import IProjectProvider
from ucp.ports.outbound.tenant_query_service import ITenantQueryService
from ucp.ports.outbound.tenant_repository import ITenantRepository

router = APIRouter(prefix="/tenants", tags=["Tenants"])


@router.get("", response_model=list[TenantResponse])
@inject
async def find_all(  # type: ignore
    _: Annotated[IdentityContext, Depends(require_platform_admin)],
    session: AsyncSession = Depends(get_db_session),
    query_service_factory=Depends(Provide[Container.tenant_query_service.provider]),
):
    query_service: ITenantQueryService = query_service_factory(session=session)
    tenants = await query_service.get_all_tenants()
    return [TenantResponse.from_read_model(t) for t in tenants]


@router.get("/roles")
@inject
async def get_roles(  # type: ignore
    _: Annotated[IdentityContext, Depends(require_platform_admin)],
    project_provider: IProjectProvider = Depends(Provide[Container.project_provider]),
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
@inject
async def find_one(  # type: ignore
    tenant_id: str,
    _: Annotated[IdentityContext, Depends(require_tenant_member)],
    session: AsyncSession = Depends(get_db_session),
    query_service_factory=Depends(Provide[Container.tenant_query_service.provider]),
):
    query_service: ITenantQueryService = query_service_factory(session=session)
    tenant_rm = await query_service.get_tenant_by_id(tenant_id)
    if not tenant_rm:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return TenantResponse.from_read_model(tenant_rm)


@router.post("", response_model=TenantResponse)
@inject
async def provision(  # type: ignore
    dto: ProvisionTenantRequest,
    _: Annotated[IdentityContext, Depends(require_platform_admin)],
    idempotency_key: str | None = Header(None, alias="idempotency-key"),
    session: AsyncSession = Depends(get_db_session),
    use_case_factory=Depends(Provide[Container.provision_tenant_use_case.provider]),
    query_service_factory=Depends(Provide[Container.tenant_query_service.provider]),
):
    use_case: ProvisionTenantUseCase = use_case_factory(uow__session=session)
    query_service: ITenantQueryService = query_service_factory(session=session)
    command = ProvisionTenantCommand(name=dto.name)
    tenant = await use_case.execute(command, idempotency_key)

    tenant_rm = await query_service.get_tenant_by_id(tenant.id)
    assert tenant_rm is not None
    return TenantResponse.from_read_model(tenant_rm)


@router.patch("/{tenant_id}/name", response_model=TenantResponse)
@inject
async def update_name(  # type: ignore
    tenant_id: str,
    dto: UpdateTenantNameRequest,
    _: Annotated[IdentityContext, Depends(require_platform_admin)],
    idempotency_key: str | None = Header(None, alias="idempotency-key"),
    session: AsyncSession = Depends(get_db_session),
    use_case_factory=Depends(Provide[Container.update_tenant_name_use_case.provider]),
    query_service_factory=Depends(Provide[Container.tenant_query_service.provider]),
):
    use_case: UpdateTenantNameUseCase = use_case_factory(uow__session=session)
    query_service: ITenantQueryService = query_service_factory(session=session)

    command = UpdateTenantNameCommand(tenant_id=tenant_id, name=dto.name)
    await use_case.execute(command, idempotency_key)

    tenant_rm = await query_service.get_tenant_by_id(tenant_id)
    assert tenant_rm is not None
    return TenantResponse.from_read_model(tenant_rm)


@router.patch("/{tenant_id}/status", response_model=TenantResponse)
@inject
async def update_status(  # type: ignore
    tenant_id: str,
    dto: UpdateTenantStatusRequest,
    _: Annotated[IdentityContext, Depends(require_platform_admin)],
    idempotency_key: str | None = Header(None, alias="idempotency-key"),
    session: AsyncSession = Depends(get_db_session),
    use_case_factory=Depends(Provide[Container.toggle_tenant_status_use_case.provider]),
    query_service_factory=Depends(Provide[Container.tenant_query_service.provider]),
):
    use_case: ToggleTenantStatusUseCase = use_case_factory(uow__session=session)
    query_service: ITenantQueryService = query_service_factory(session=session)

    command = ToggleTenantStatusCommand(tenant_id=tenant_id, status=dto.status)
    await use_case.execute(command, idempotency_key)

    tenant_rm = await query_service.get_tenant_by_id(tenant_id)
    assert tenant_rm is not None
    return TenantResponse.from_read_model(tenant_rm)


@router.delete("/{tenant_id}", status_code=204)
@inject
async def remove(  # type: ignore
    tenant_id: str,
    _: Annotated[IdentityContext, Depends(require_platform_admin)],
    idempotency_key: str | None = Header(None, alias="idempotency-key"),
    session: AsyncSession = Depends(get_db_session),
    tenant_repo_factory=Depends(Provide[Container.tenant_repo.provider]),
    use_case_factory=Depends(Provide[Container.delete_tenant_use_case.provider]),
):
    tenant_repo: ITenantRepository = tenant_repo_factory(session=session)
    use_case: DeleteTenantUseCase = use_case_factory(
        uow__session=session,
    )
    tenant = await resolve_tenant(tenant_id, tenant_repo)
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
@inject
async def get_subscriptions(
    id: str,
    _: Annotated[IdentityContext, Depends(require_platform_admin)],
    session: AsyncSession = Depends(get_db_session),
    tenant_repo_factory: Any = Depends(Provide[Container.tenant_repo.provider]),
) -> list[SubscriptionResponse]:
    tenant_repo: ITenantRepository = tenant_repo_factory(session=session)
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
@inject
async def subscribe_app(
    id: str,
    dto: SubscribeAppRequest,
    _: Annotated[IdentityContext, Depends(require_platform_admin)],
    idempotency_key: str | None = Header(None, alias="idempotency-key"),
    session: AsyncSession = Depends(get_db_session),
    tenant_repo_factory: Any = Depends(Provide[Container.tenant_repo.provider]),
) -> SubscriptionResponse:
    tenant_repo: ITenantRepository = tenant_repo_factory(session=session)
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
@inject
async def unsubscribe_app(
    id: str,
    app_id: str,
    _: Annotated[IdentityContext, Depends(require_platform_admin)],
    idempotency_key: str | None = Header(None, alias="idempotency-key"),
    session: AsyncSession = Depends(get_db_session),
    tenant_repo_factory: Any = Depends(Provide[Container.tenant_repo.provider]),
) -> dict[str, bool]:
    tenant_repo: ITenantRepository = tenant_repo_factory(session=session)
    tenant = await resolve_tenant(id, tenant_repo)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    try:
        tenant.unsubscribe_from_app(app_id)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(e))

    await tenant_repo.save(tenant, idempotency_key)
    return {"success": True}
