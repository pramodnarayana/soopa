from collections.abc import Callable
from typing import Annotated, Any, Literal, cast

import structlog
from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from identity.domain.identity_context import IdentityContext
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

from identity.domain.models.authorization import Capability
from identity.ports.outbound.role_repository_port import RoleRepositoryPort
from ucp.application.dto import SubscribeAppCommand, UnsubscribeAppCommand
from ucp.application.use_cases.delete_tenant_use_case import DeleteTenantUseCase
from ucp.application.use_cases.provision_tenant_use_case import (
    ProvisionTenantCommand,
    ProvisionTenantUseCase,
)
from ucp.application.use_cases.subscribe_app_use_case import (
    SubscribeAppUseCase,
)
from ucp.application.use_cases.toggle_tenant_status_use_case import (
    ToggleTenantStatusCommand,
    ToggleTenantStatusUseCase,
)
from ucp.application.use_cases.unsubscribe_app_use_case import (
    UnsubscribeAppUseCase,
)
from ucp.application.use_cases.update_tenant_name_use_case import (
    UpdateTenantNameCommand,
    UpdateTenantNameUseCase,
)
from ucp.bootstrap.container import Container
from ucp.bootstrap.dependencies import get_db_session
from ucp.domain.exceptions import ResourceNotFoundError
from ucp.domain.models.tenant import Tenant
from ucp.ports.outbound.tenant_query_service_port import TenantQueryServicePort
from ucp.ports.outbound.tenant_repository_port import TenantRepositoryPort

from unified_api.adapters.inbound.http.dtos.tenant_dtos import (
    ProvisionTenantRequest,
    TenantResponse,
    UpdateTenantNameRequest,
    UpdateTenantStatusRequest,
)
from unified_api.adapters.inbound.http.guards.require_capability_guard import RequireCapability
from unified_api.adapters.inbound.http.guards.tenant_auth_guard import require_tenant_member

router = APIRouter(prefix="/tenants", tags=["Tenants"])


class PaginatedTenantsResponse(BaseModel):
    items: list[TenantResponse]
    total: int
    page: int
    limit: int


class RoleResponse(BaseModel):
    id: str
    name: str
    description: str | None
    capabilities: list[str]


@router.get(
    "",
    response_model=PaginatedTenantsResponse,
    dependencies=[Depends(RequireCapability(Capability.PLATFORM_ADMIN))],
)
@inject
async def find_all(
    request: Request,
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    limit: int = Query(50, ge=1, le=1000, description="Items per page"),
    session: AsyncSession = Depends(get_db_session),
    query_service_factory: Callable[..., TenantQueryServicePort] = Depends(
        Provide[Container.tenant_query_service.provider]
    ),
) -> PaginatedTenantsResponse:
    query_service: TenantQueryServicePort = query_service_factory(session=session)
    paginated = await query_service.get_all_tenants(page=page, limit=limit)
    return PaginatedTenantsResponse(
        items=[TenantResponse.from_read_model(t) for t in paginated.items],
        total=paginated.total,
        page=paginated.page,
        limit=paginated.limit,
    )


@router.get(
    "/roles",
    response_model=list[RoleResponse],
    dependencies=[Depends(RequireCapability(Capability.PLATFORM_ADMIN))],
)
@inject
async def get_roles(
    request: Request,
    session: AsyncSession = Depends(get_db_session),
    role_repo_factory: Any = Depends(Provide[Container.role_repo.provider]),
) -> list[RoleResponse]:
    role_repository: RoleRepositoryPort = role_repo_factory(session=session)
    roles = await role_repository.get_global_roles()
    return [
        RoleResponse(
            id=role.id, name=role.name, description=role.description, capabilities=role.capabilities
        )
        for role in roles
    ]


async def resolve_tenant(id: str, tenant_repo: TenantRepositoryPort) -> "Tenant":
    tenant = await tenant_repo.find_by_id(id)
    if not tenant:
        tenant = await tenant_repo.find_by_idp_tenant_id(id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


@router.get(
    "/{tenant_id}",
    response_model=TenantResponse,
    dependencies=[Depends(RequireCapability(Capability.TENANT_SETTINGS_READ))],
)
@inject
async def find_one(
    tenant_id: str,
    _: Annotated[IdentityContext, Depends(require_tenant_member)],
    session: AsyncSession = Depends(get_db_session),
    query_service_factory: Callable[..., TenantQueryServicePort] = Depends(
        Provide[Container.tenant_query_service.provider]
    ),
) -> TenantResponse:
    query_service: TenantQueryServicePort = query_service_factory(session=session)
    tenant_rm = await query_service.get_tenant_by_id(tenant_id)
    if not tenant_rm:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return TenantResponse.from_read_model(tenant_rm)


@router.post(
    "",
    response_model=TenantResponse,
    dependencies=[Depends(RequireCapability(Capability.PLATFORM_ADMIN))],
)
@inject
async def provision(
    request: Request,
    dto: ProvisionTenantRequest,
    idempotency_key: str | None = Header(None, alias="idempotency-key"),
    session: AsyncSession = Depends(get_db_session),
    use_case_factory: Callable[..., ProvisionTenantUseCase] = Depends(
        Provide[Container.provision_tenant_use_case.provider]
    ),
    query_service_factory: Callable[..., TenantQueryServicePort] = Depends(
        Provide[Container.tenant_query_service.provider]
    ),
) -> TenantResponse:
    use_case: ProvisionTenantUseCase = use_case_factory(uow__session=session)
    query_service: TenantQueryServicePort = query_service_factory(session=session)

    # We enforce PLATFORM_ADMIN capability, so request.state.identity is guaranteed to be present
    identity: IdentityContext = request.state.identity
    creator_id = identity.subject

    if not creator_id or not creator_id.startswith("usr_"):
        raise HTTPException(
            status_code=400,
            detail="Invalid user identity: creator must be a resolved platform user ID (usr_...)",
        )

    command = ProvisionTenantCommand(name=dto.name, creator_id=creator_id)
    tenant = await use_case.execute(command, idempotency_key)

    tenant_rm = await query_service.get_tenant_by_id(tenant.id)
    assert tenant_rm is not None
    return TenantResponse.from_read_model(tenant_rm)


@router.patch(
    "/{tenant_id}/name",
    response_model=TenantResponse,
    dependencies=[Depends(RequireCapability(Capability.PLATFORM_ADMIN))],
)
@inject
async def update_name(
    request: Request,
    tenant_id: str,
    dto: UpdateTenantNameRequest,
    idempotency_key: str | None = Header(None, alias="idempotency-key"),
    session: AsyncSession = Depends(get_db_session),
    use_case_factory: Callable[..., UpdateTenantNameUseCase] = Depends(
        Provide[Container.update_tenant_name_use_case.provider]
    ),
    query_service_factory: Callable[..., TenantQueryServicePort] = Depends(
        Provide[Container.tenant_query_service.provider]
    ),
) -> TenantResponse:
    use_case: UpdateTenantNameUseCase = use_case_factory(uow__session=session)
    query_service: TenantQueryServicePort = query_service_factory(session=session)

    command = UpdateTenantNameCommand(tenant_id=tenant_id, name=dto.name)
    await use_case.execute(command, idempotency_key)

    tenant_rm = await query_service.get_tenant_by_id(tenant_id)
    assert tenant_rm is not None
    return TenantResponse.from_read_model(tenant_rm)


@router.patch(
    "/{tenant_id}/status",
    response_model=TenantResponse,
    dependencies=[Depends(RequireCapability(Capability.PLATFORM_ADMIN))],
)
@inject
async def update_status(
    request: Request,
    tenant_id: str,
    dto: UpdateTenantStatusRequest,
    idempotency_key: str | None = Header(None, alias="idempotency-key"),
    session: AsyncSession = Depends(get_db_session),
    use_case_factory: Callable[..., ToggleTenantStatusUseCase] = Depends(
        Provide[Container.toggle_tenant_status_use_case.provider]
    ),
    query_service_factory: Callable[..., TenantQueryServicePort] = Depends(
        Provide[Container.tenant_query_service.provider]
    ),
) -> TenantResponse:
    use_case: ToggleTenantStatusUseCase = use_case_factory(uow__session=session)
    query_service: TenantQueryServicePort = query_service_factory(session=session)

    command = ToggleTenantStatusCommand(
        tenant_id=tenant_id, status=cast(Literal["active", "inactive"], dto.status)
    )
    await use_case.execute(command, idempotency_key)

    tenant_rm = await query_service.get_tenant_by_id(tenant_id)
    assert tenant_rm is not None
    return TenantResponse.from_read_model(tenant_rm)


@router.delete(
    "/{tenant_id}",
    status_code=204,
    dependencies=[Depends(RequireCapability(Capability.PLATFORM_ADMIN))],
)
@inject
async def remove(
    request: Request,
    tenant_id: str,
    idempotency_key: str | None = Header(None, alias="idempotency-key"),
    session: AsyncSession = Depends(get_db_session),
    tenant_repo_factory: Callable[..., TenantRepositoryPort] = Depends(
        Provide[Container.tenant_repo.provider]
    ),
    use_case_factory: Callable[..., DeleteTenantUseCase] = Depends(
        Provide[Container.delete_tenant_use_case.provider]
    ),
) -> None:
    tenant_repo: TenantRepositoryPort = tenant_repo_factory(session=session)
    use_case: DeleteTenantUseCase = use_case_factory(
        uow__session=session,
    )
    tenant = await resolve_tenant(tenant_id, tenant_repo)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    await use_case.execute(tenant.id, idempotency_key)
    return None


class SubscribeAppRequest(BaseModel):
    appId: str


class SubscriptionResponse(BaseModel):
    id: str
    appId: str
    tenantId: str
    status: str


@router.get(
    "/{id}/subscriptions",
    response_model=list[SubscriptionResponse],
    dependencies=[Depends(RequireCapability(Capability.PLATFORM_ADMIN))],
)
@inject
async def get_subscriptions(
    request: Request,
    id: str,
    session: AsyncSession = Depends(get_db_session),
    tenant_repo_factory: Any = Depends(Provide[Container.tenant_repo.provider]),
) -> list[SubscriptionResponse]:
    tenant_repo: TenantRepositoryPort = tenant_repo_factory(session=session)
    tenant = await resolve_tenant(id, tenant_repo)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    return [
        SubscriptionResponse(
            id=f"{tenant.id}_{sub.app_id}", appId=sub.app_id, tenantId=tenant.id, status=sub.status
        )
        for sub in tenant.subscriptions
    ]


@router.post(
    "/{id}/subscriptions",
    response_model=SubscriptionResponse,
    dependencies=[Depends(RequireCapability(Capability.PLATFORM_ADMIN))],
)
@inject
async def subscribe_app(
    request: Request,
    id: str,
    dto: SubscribeAppRequest,
    idempotency_key: str | None = Header(None, alias="idempotency-key"),
    session: AsyncSession = Depends(get_db_session),
    use_case_factory: Any = Depends(Provide[Container.subscribe_app_use_case.provider]),
) -> SubscriptionResponse:
    use_case: SubscribeAppUseCase = use_case_factory(uow__session=session)
    command = SubscribeAppCommand(tenant_id=id, app_id=dto.appId)

    try:
        await use_case.execute(command, idempotency_key)
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.exception("app_subscription_failed", tenant_id=id, app_id=dto.appId)
        raise HTTPException(status_code=400, detail="Subscription failed") from e

    return SubscriptionResponse(
        id=f"{id}_{dto.appId}", appId=dto.appId, tenantId=id, status="active"
    )


@router.delete(
    "/{id}/subscriptions/{app_id}",
    dependencies=[Depends(RequireCapability(Capability.PLATFORM_ADMIN))],
)
@inject
async def unsubscribe_app(
    request: Request,
    id: str,
    app_id: str,
    idempotency_key: str | None = Header(None, alias="idempotency-key"),
    session: AsyncSession = Depends(get_db_session),
    use_case_factory: Any = Depends(Provide[Container.unsubscribe_app_use_case.provider]),
) -> dict[str, bool]:
    use_case: UnsubscribeAppUseCase = use_case_factory(uow__session=session)
    command = UnsubscribeAppCommand(tenant_id=id, app_id=app_id)

    try:
        await use_case.execute(command, idempotency_key)
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.exception("app_unsubscription_failed", tenant_id=id, app_id=app_id)
        raise HTTPException(status_code=400, detail="Unsubscription failed") from e

    return {"success": True}
