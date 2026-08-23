from collections.abc import Callable
from typing import Annotated, Any

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Path, Request
from identity.domain.identity_context import IdentityContext
from sqlalchemy.ext.asyncio import AsyncSession
from ucp.application.use_cases.create_user_use_case import (
    CreateUserCommand,
    CreateUserUseCase,
)
from ucp.application.use_cases.delete_user_use_case import (
    DeleteUserCommand,
    DeleteUserUseCase,
)
from ucp.application.use_cases.toggle_user_status_use_case import (
    ToggleUserStatusCommand,
    ToggleUserStatusUseCase,
)
from ucp.application.use_cases.update_user_use_case import (
    UpdateUserCommand,
    UpdateUserUseCase,
)
from ucp.bootstrap.container import Container
from ucp.bootstrap.dependencies import get_db_session
from ucp.domain.exceptions import ResourceNotFoundError
from ucp.domain.models.authorization import Capability
from ucp.ports.outbound.tenant_repository_port import TenantRepositoryPort
from ucp.ports.outbound.user_repository_port import UserRepositoryPort

from unified_api.adapters.inbound.http.dtos.user_dtos import (
    CreateUserRequest,
    ToggleUserStatusRequest,
    UpdateUserRequest,
)
from unified_api.adapters.inbound.http.guards.require_capability_guard import RequireCapability
from unified_api.adapters.inbound.http.guards.tenant_auth_guard import require_tenant_member

router = APIRouter(prefix="/tenants/{tenant_id}/users", tags=["Users"])


@router.get("", dependencies=[Depends(RequireCapability(Capability.USERS_READ))])
@inject
async def get_users(
    request: Request,
    _: Annotated[IdentityContext, Depends(require_tenant_member)],
    tenant_id: str = Path(...),
    session: AsyncSession = Depends(get_db_session),
    tenant_repo_factory: Callable[..., TenantRepositoryPort] = Depends(
        Provide[Container.tenant_repo.provider]
    ),
    user_repo_factory: Callable[..., UserRepositoryPort] = Depends(
        Provide[Container.user_repo.provider]
    ),
) -> dict[str, list[dict[str, Any]]]:
    tenant_repo: TenantRepositoryPort = tenant_repo_factory(session=session)
    user_repo: UserRepositoryPort = user_repo_factory(session=session)
    canonical_tenant_id = request.state.ucp_tenant_id
    tenant = await tenant_repo.find_by_id(canonical_tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    users = await user_repo.find_users_by_tenant(canonical_tenant_id)

    result = []
    for u in users:
        name_parts = u.name.split(" ")
        first_name = name_parts[0] if name_parts else ""
        last_name = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

        result.append(
            {
                "id": u.id,
                "email": u.email,
                "displayName": u.name,
                "firstName": first_name,
                "lastName": last_name,
                "state": "USER_STATE_INACTIVE" if u.status == "inactive" else "USER_STATE_ACTIVE",
                "role": getattr(u, "role", "Unknown"),
                "createdAt": u.created_at.isoformat(),
            }
        )

    return {"result": result}


@router.post("", dependencies=[Depends(RequireCapability(Capability.USERS_WRITE))])
@inject
async def create_user(
    request: Request,
    dto: CreateUserRequest,
    _: Annotated[IdentityContext, Depends(require_tenant_member)],
    tenant_id: str = Path(...),
    session: AsyncSession = Depends(get_db_session),
    use_case_factory: Callable[..., CreateUserUseCase] = Depends(
        Provide[Container.create_user_use_case.provider]
    ),
) -> dict[str, str]:
    use_case: CreateUserUseCase = use_case_factory(uow__session=session)
    canonical_tenant_id = request.state.ucp_tenant_id
    command = CreateUserCommand(
        tenant_id=canonical_tenant_id,
        email=dto.email,
        first_name=dto.first_name,
        last_name=dto.last_name,
        role=dto.role,
    )

    try:
        user_id = await use_case.execute(command)
        return {"userId": user_id}
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/{user_id}", dependencies=[Depends(RequireCapability(Capability.USERS_WRITE))])
@inject
async def update_user(
    request: Request,
    dto: UpdateUserRequest,
    _: Annotated[IdentityContext, Depends(require_tenant_member)],
    tenant_id: str = Path(...),
    user_id: str = Path(...),
    session: AsyncSession = Depends(get_db_session),
    use_case_factory: Callable[..., UpdateUserUseCase] = Depends(
        Provide[Container.update_user_use_case.provider]
    ),
) -> dict[str, bool]:
    use_case: UpdateUserUseCase = use_case_factory(uow__session=session)
    canonical_tenant_id = request.state.ucp_tenant_id
    command = UpdateUserCommand(
        tenant_id=canonical_tenant_id,
        user_id=user_id,
        first_name=dto.first_name,
        last_name=dto.last_name,
        role=dto.role,
    )

    try:
        await use_case.execute(command)
        return {"success": True}
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch(
    "/{user_id}/status", dependencies=[Depends(RequireCapability(Capability.USERS_WRITE))]
)
@inject
async def toggle_status(
    request: Request,
    dto: ToggleUserStatusRequest,
    _: Annotated[IdentityContext, Depends(require_tenant_member)],
    tenant_id: str = Path(...),
    user_id: str = Path(...),
    session: AsyncSession = Depends(get_db_session),
    use_case_factory: Callable[..., ToggleUserStatusUseCase] = Depends(
        Provide[Container.toggle_user_status_use_case.provider]
    ),
) -> dict[str, bool]:
    use_case: ToggleUserStatusUseCase = use_case_factory(uow__session=session)
    canonical_tenant_id = request.state.ucp_tenant_id
    command = ToggleUserStatusCommand(
        tenant_id=canonical_tenant_id,
        user_id=user_id,
        action=dto.action,
    )

    try:
        await use_case.execute(command)
        return {"success": True}
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{user_id}", dependencies=[Depends(RequireCapability(Capability.USERS_WRITE))])
@inject
async def delete_user(
    request: Request,
    _: Annotated[IdentityContext, Depends(require_tenant_member)],
    tenant_id: str = Path(...),
    user_id: str = Path(...),
    session: AsyncSession = Depends(get_db_session),
    use_case_factory: Callable[..., DeleteUserUseCase] = Depends(
        Provide[Container.delete_user_use_case.provider]
    ),
) -> dict[str, bool]:
    use_case: DeleteUserUseCase = use_case_factory(uow__session=session)
    canonical_tenant_id = request.state.ucp_tenant_id
    command = DeleteUserCommand(
        tenant_id=canonical_tenant_id,
        user_id=user_id,
    )

    try:
        await use_case.execute(command)
        return {"success": True}
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
