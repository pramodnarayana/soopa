from typing import Annotated, Any

from dependency_injector.wiring import Provide, inject
from fastapi import APIRouter, Depends, HTTPException, status
from identity.domain.identity_context import IdentityContext
from sqlalchemy.ext.asyncio import AsyncSession

from ucp.adapters.inbound.http.dtos.api_token_dtos import (
    ApiTokenCreatedResponse,
    ApiTokenResponse,
    CreateApiTokenRequest,
    UpdateApiTokenRequest,
)
from ucp.adapters.inbound.http.guards.tenant_auth_guard import require_tenant_member
from ucp.application.models.api_token_models import (
    CreateApiTokenCommand,
    UpdateApiTokenCommand,
)
from ucp.application.use_cases.api_tokens import (
    CreateApiTokenUseCase,
    DeleteApiTokenUseCase,
    ListApiTokensUseCase,
    UpdateApiTokenUseCase,
)
from ucp.bootstrap.container import Container
from ucp.core.container import get_db_session

# This is mounted under /tenants/{tenant_id}/tokens, but we define the prefix at include_router
router = APIRouter(tags=["API Tokens"])


@router.get("", response_model=list[ApiTokenResponse], status_code=status.HTTP_200_OK)
@inject
async def list_tokens(
    tenant_id: str,
    context: Annotated[IdentityContext, Depends(require_tenant_member)],
    session: AsyncSession = Depends(get_db_session),
    use_case_factory: Any = Depends(Provide[Container.list_api_tokens_use_case.provider]),
) -> list[ApiTokenResponse]:
    """Lists all active and inactive API tokens for the tenant."""
    use_case: ListApiTokensUseCase = use_case_factory(uow__session=session)
    tokens = await use_case.execute(tenant_id)
    return [ApiTokenResponse.model_validate(t) for t in tokens]


@router.post("", response_model=ApiTokenCreatedResponse, status_code=status.HTTP_201_CREATED)
@inject
async def create_token(
    tenant_id: str,
    request: CreateApiTokenRequest,
    context: Annotated[IdentityContext, Depends(require_tenant_member)],
    session: AsyncSession = Depends(get_db_session),
    use_case_factory: Any = Depends(Provide[Container.create_api_token_use_case.provider]),
) -> ApiTokenCreatedResponse:
    """
    Creates a new API Token.
    The raw secret is only returned ONCE in this response.
    """
    use_case: CreateApiTokenUseCase = use_case_factory(uow__session=session)
    command = CreateApiTokenCommand(name=request.name, expires_at=request.expires_at)
    result = await use_case.execute(tenant_id, command)
    return ApiTokenCreatedResponse(
        id=result.id,
        name=result.name,
        client_id=result.client_id,
        active=result.active,
        last_used_at=result.last_used_at,
        expires_at=result.expires_at,
        created_at=result.created_at,
        token=result.token,
    )


@router.patch("/{token_id}", response_model=ApiTokenResponse, status_code=status.HTTP_200_OK)
@inject
async def update_token(
    tenant_id: str,
    token_id: str,
    request: UpdateApiTokenRequest,
    context: Annotated[IdentityContext, Depends(require_tenant_member)],
    session: AsyncSession = Depends(get_db_session),
    use_case_factory: Any = Depends(Provide[Container.update_api_token_use_case.provider]),
) -> ApiTokenResponse:
    """Updates token metadata (e.g. name or active status)."""
    use_case: UpdateApiTokenUseCase = use_case_factory(uow__session=session)
    command = UpdateApiTokenCommand(name=request.name, active=request.active)
    token = await use_case.execute(token_id, tenant_id, command)
    if not token:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found")
    return ApiTokenResponse.model_validate(token)


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
@inject
async def delete_token(
    tenant_id: str,
    token_id: str,
    context: Annotated[IdentityContext, Depends(require_tenant_member)],
    session: AsyncSession = Depends(get_db_session),
    use_case_factory: Any = Depends(Provide[Container.delete_api_token_use_case.provider]),
) -> None:
    """Permanently deletes an API token."""
    use_case: DeleteApiTokenUseCase = use_case_factory(uow__session=session)
    deleted = await use_case.execute(token_id, tenant_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found")
