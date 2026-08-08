from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from identity.domain.identity_context import IdentityContext

from ucp.adapters.inbound.http.dtos.api_token_dtos import (
    ApiTokenCreatedResponse,
    ApiTokenResponse,
    CreateApiTokenRequest,
    UpdateApiTokenRequest,
)
from ucp.adapters.inbound.http.guards.tenant_auth_guard import require_tenant_member
from ucp.application.services.api_token_service import ApiTokenService

# This is mounted under /tenants/{tenant_id}/tokens, but we define the prefix at include_router
router = APIRouter(tags=["API Tokens"])


def get_api_token_service() -> ApiTokenService:
    raise NotImplementedError()


@router.get("", response_model=list[ApiTokenResponse], status_code=status.HTTP_200_OK)
async def list_tokens(
    tenant_id: str,
    context: Annotated[IdentityContext, Depends(require_tenant_member)],
    service: Annotated[ApiTokenService, Depends(get_api_token_service)],
) -> list[ApiTokenResponse]:
    """Lists all active and inactive API tokens for the tenant."""
    tokens = await service.list_tokens(tenant_id)
    return [ApiTokenResponse.model_validate(t) for t in tokens]


@router.post("", response_model=ApiTokenCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_token(
    tenant_id: str,
    request: CreateApiTokenRequest,
    context: Annotated[IdentityContext, Depends(require_tenant_member)],
    service: Annotated[ApiTokenService, Depends(get_api_token_service)],
) -> ApiTokenCreatedResponse:
    """
    Creates a new API Token.
    The raw secret is only returned ONCE in this response.
    """
    return await service.create_token(tenant_id, request)


@router.patch("/{token_id}", response_model=ApiTokenResponse, status_code=status.HTTP_200_OK)
async def update_token(
    tenant_id: str,
    token_id: str,
    request: UpdateApiTokenRequest,
    context: Annotated[IdentityContext, Depends(require_tenant_member)],
    service: Annotated[ApiTokenService, Depends(get_api_token_service)],
) -> ApiTokenResponse:
    """Updates token metadata (e.g. name or active status)."""
    token = await service.update_token(token_id, tenant_id, request)
    if not token:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found")
    return ApiTokenResponse.model_validate(token)


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_token(
    tenant_id: str,
    token_id: str,
    context: Annotated[IdentityContext, Depends(require_tenant_member)],
    service: Annotated[ApiTokenService, Depends(get_api_token_service)],
) -> None:
    """Permanently deletes an API token."""
    deleted = await service.delete_token(token_id, tenant_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Token not found")
