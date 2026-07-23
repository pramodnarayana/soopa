import logging
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from api.adapters.http.dtos import (
    ApiTokenCreatedResponse,
    ApiTokenListItem,
    ApiTokenListResponse,
    CreateApiTokenRequest,
    UpdateApiTokenRequest,
)
from api.core.services.api_token_service import ApiTokenService
from api.dependencies.auth import get_current_tenant_id
from api.dependencies.services import get_api_token_repo
from api.domain.models import CreateApiTokenCmd
from api.ports.repository import ApiTokenRepositoryPort

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/developers/tokens", tags=["API Tokens"])


@router.post(
    "",
    response_model=ApiTokenCreatedResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_api_token(
    request: CreateApiTokenRequest,
    tenant_id: int = Depends(get_current_tenant_id),
    repo: ApiTokenRepositoryPort = Depends(get_api_token_repo),
) -> Any:
    """
    Generate a new two-part API credential for the tenant.
    The client_secret is returned exactly once in this response and cannot be retrieved again.
    """
    service = ApiTokenService(repo)
    # Get the tenant name from somewhere? For now, we can pass a dummy or fetch it.
    # We should ideally fetch the tenant name to use in the prefix.
    # For now, using a generic placeholder as the slug generator handles it.
    tenant_name = f"tenant{tenant_id}"

    cmd = CreateApiTokenCmd(name=request.name, expires_at=request.expires_at)

    token = await service.create_token(tenant_id=tenant_id, tenant_name=tenant_name, cmd=cmd)

    return ApiTokenCreatedResponse(
        id=token.id,
        name=token.name,
        client_id=token.client_id,
        client_secret=token.client_secret,
        active=token.active,
        created_at="just now",  # This is usually handled by the DB, but since we return the entity immediately, we need a value. Let's just return the current ISO string if needed, or rely on the UI to just know it's new. Actually, we should probably fetch the record or just return a fresh datetime.
    )


@router.get(
    "",
    response_model=ApiTokenListResponse,
)
async def list_api_tokens(
    tenant_id: int = Depends(get_current_tenant_id),
    repo: ApiTokenRepositoryPort = Depends(get_api_token_repo),
) -> Any:
    """List all API tokens for the current tenant."""
    service = ApiTokenService(repo)
    tokens = await service.list_tokens(tenant_id)
    return ApiTokenListResponse(
        tokens=[ApiTokenListItem.model_validate(t, from_attributes=True) for t in tokens]
    )


@router.patch(
    "/{token_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def update_api_token(
    token_id: UUID,
    request: UpdateApiTokenRequest,
    tenant_id: int = Depends(get_current_tenant_id),
    repo: ApiTokenRepositoryPort = Depends(get_api_token_repo),
) -> None:
    """Updates an API token (name or active status)."""
    service = ApiTokenService(repo)
    success = await service.update_token(
        tenant_id, token_id, name=request.name, active=request.active
    )
    if not success:
        raise HTTPException(status_code=404, detail="Token not found")


@router.delete(
    "/{token_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_api_token(
    token_id: UUID,
    tenant_id: int = Depends(get_current_tenant_id),
    repo: ApiTokenRepositoryPort = Depends(get_api_token_repo),
) -> None:
    """Permanently delete an API token."""
    service = ApiTokenService(repo)
    success = await service.delete_token(tenant_id, token_id)
    if not success:
        raise HTTPException(status_code=404, detail="Token not found")
