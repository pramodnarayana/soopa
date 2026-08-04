from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Request

from identity.domain.identity_context import IdentityContext
from ucp_api.adapters.inbound.http.dtos.user_dtos import (
    CreateUserRequest,
    ToggleUserStatusRequest,
    UpdateUserRequest,
)
from ucp_api.adapters.inbound.http.guards.tenant_auth_guard import require_tenant_member
from ucp_api.application.use_cases.delete_user_use_case import (
    DeleteUserCommand,
    DeleteUserUseCase,
)
from ucp_api.application.use_cases.invite_user_use_case import (
    InviteUserCommand,
    InviteUserUseCase,
)
from ucp_api.application.use_cases.toggle_user_status_use_case import (
    ToggleUserStatusCommand,
    ToggleUserStatusUseCase,
)
from ucp_api.application.use_cases.update_user_use_case import (
    UpdateUserCommand,
    UpdateUserUseCase,
)
from ucp_api.core.exceptions import ResourceNotFoundError
from ucp_api.ports.outbound.tenant_repository import ITenantRepository
from ucp_api.ports.outbound.user_repository import IUserRepository

router = APIRouter(prefix="/tenants/{tenant_id}/users", tags=["Users"])


# Dependency placeholders \u2014 overridden in main.py via dependency_overrides
def get_tenant_repo() -> ITenantRepository:
    raise NotImplementedError()


def get_user_repo() -> IUserRepository:
    raise NotImplementedError()


def get_invite_user_use_case() -> InviteUserUseCase:
    raise NotImplementedError()


def get_update_user_use_case() -> UpdateUserUseCase:
    raise NotImplementedError()


def get_toggle_user_status_use_case() -> ToggleUserStatusUseCase:
    raise NotImplementedError()


def get_delete_user_use_case() -> DeleteUserUseCase:
    raise NotImplementedError()


@router.get("/")
async def get_users(  # type: ignore
    request: Request,
    _: Annotated[IdentityContext, Depends(require_tenant_member)],
    tenant_id: str = Path(...),
    tenant_repo: ITenantRepository = Depends(get_tenant_repo),
    user_repo: IUserRepository = Depends(get_user_repo),
):
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


@router.post("/")
async def create_user(  # type: ignore
    request: Request,
    dto: CreateUserRequest,
    _: Annotated[IdentityContext, Depends(require_tenant_member)],
    tenant_id: str = Path(...),
    use_case: InviteUserUseCase = Depends(get_invite_user_use_case),
):
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
async def update_user(  # type: ignore
    request: Request,
    dto: UpdateUserRequest,
    _: Annotated[IdentityContext, Depends(require_tenant_member)],
    tenant_id: str = Path(...),
    user_id: str = Path(...),
    use_case: UpdateUserUseCase = Depends(get_update_user_use_case),
):
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
async def toggle_status(  # type: ignore
    request: Request,
    dto: ToggleUserStatusRequest,
    _: Annotated[IdentityContext, Depends(require_tenant_member)],
    tenant_id: str = Path(...),
    user_id: str = Path(...),
    use_case: ToggleUserStatusUseCase = Depends(get_toggle_user_status_use_case),
):
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
async def delete_user(  # type: ignore
    request: Request,
    _: Annotated[IdentityContext, Depends(require_tenant_member)],
    tenant_id: str = Path(...),
    user_id: str = Path(...),
    use_case: DeleteUserUseCase = Depends(get_delete_user_use_case),
):
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
