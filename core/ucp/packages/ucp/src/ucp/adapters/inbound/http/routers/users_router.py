from typing import Annotated

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, Path, Request
from identity.domain.identity_context import IdentityContext
from sqlalchemy.ext.asyncio import AsyncSession

from ucp.adapters.inbound.http.dtos.user_dtos import (
    CreateUserRequest,
    ToggleUserStatusRequest,
    UpdateUserRequest,
)
from ucp.adapters.inbound.http.guards.tenant_auth_guard import require_tenant_member
from ucp.application.use_cases.delete_user_use_case import (
    DeleteUserCommand,
    DeleteUserUseCase,
)
from ucp.application.use_cases.invite_user_use_case import (
    InviteUserCommand,
    InviteUserUseCase,
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
from ucp.core.container import get_db_session
from ucp.core.exceptions import ResourceNotFoundError
from ucp.ports.outbound.tenant_repository import ITenantRepository
from ucp.ports.outbound.user_repository import IUserRepository

router = APIRouter(prefix="/tenants/{tenant_id}/users", tags=["Users"])


@router.get("")
@inject
async def get_users(  # type: ignore
    request: Request,
    _: Annotated[IdentityContext, Depends(require_tenant_member)],
    tenant_id: str = Path(...),
    session: AsyncSession = Depends(get_db_session),
    tenant_repo_factory=Depends(Provide[Container.tenant_repo.provider]),
    user_repo_factory=Depends(Provide[Container.user_repo.provider]),
):
    tenant_repo: ITenantRepository = tenant_repo_factory(session=session)
    user_repo: IUserRepository = user_repo_factory(session=session)
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


@router.post("")
@inject
async def create_user(  # type: ignore
    request: Request,
    dto: CreateUserRequest,
    _: Annotated[IdentityContext, Depends(require_tenant_member)],
    tenant_id: str = Path(...),
    session: AsyncSession = Depends(get_db_session),
    use_case_factory=Depends(Provide[Container.invite_user_use_case.provider]),
):
    use_case: InviteUserUseCase = use_case_factory(
        tenant_repo__session=session,
        user_repo__session=session,
    )
    canonical_tenant_id = request.state.ucp_tenant_id
    command = InviteUserCommand(
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


@router.patch("/{user_id}")
@inject
async def update_user(  # type: ignore
    request: Request,
    dto: UpdateUserRequest,
    _: Annotated[IdentityContext, Depends(require_tenant_member)],
    tenant_id: str = Path(...),
    user_id: str = Path(...),
    session: AsyncSession = Depends(get_db_session),
    use_case_factory=Depends(Provide[Container.update_user_use_case.provider]),
):
    use_case: UpdateUserUseCase = use_case_factory(
        tenant_repo__session=session,
        user_repo__session=session,
    )
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


@router.patch("/{user_id}/status")
@inject
async def toggle_status(  # type: ignore
    request: Request,
    dto: ToggleUserStatusRequest,
    _: Annotated[IdentityContext, Depends(require_tenant_member)],
    tenant_id: str = Path(...),
    user_id: str = Path(...),
    session: AsyncSession = Depends(get_db_session),
    use_case_factory=Depends(Provide[Container.toggle_user_status_use_case.provider]),
):
    use_case: ToggleUserStatusUseCase = use_case_factory(
        tenant_repo__session=session,
        user_repo__session=session,
    )
    canonical_tenant_id = request.state.ucp_tenant_id
    command = ToggleUserStatusCommand(
        tenant_id=canonical_tenant_id,
        user_id=user_id,
        action=dto.action,  # type: ignore
    )

    try:
        await use_case.execute(command)
        return {"success": True}
    except ResourceNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/{user_id}")
@inject
async def delete_user(  # type: ignore
    request: Request,
    _: Annotated[IdentityContext, Depends(require_tenant_member)],
    tenant_id: str = Path(...),
    user_id: str = Path(...),
    session: AsyncSession = Depends(get_db_session),
    use_case_factory=Depends(Provide[Container.delete_user_use_case.provider]),
):
    use_case: DeleteUserUseCase = use_case_factory(
        tenant_repo__session=session,
        user_repo__session=session,
    )
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
