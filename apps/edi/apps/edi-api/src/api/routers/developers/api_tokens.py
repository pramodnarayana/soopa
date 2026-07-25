import logging
from typing import Any

from fastapi import APIRouter, Depends

from api.adapters.http.dtos import (
    ApiTokenListItem,
    ApiTokenListResponse,
)
from api.core.services.api_token_service import ApiTokenService
from api.dependencies.auth import get_current_tenant_id
from api.dependencies.services import get_api_token_repo
from api.ports.repository import ApiTokenRepositoryPort

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/developers/tokens", tags=["API Tokens"])



@router.get(
    "",
    response_model=ApiTokenListResponse,
)
async def list_api_tokens(
    tenant_id: str = Depends(get_current_tenant_id),
    repo: ApiTokenRepositoryPort = Depends(get_api_token_repo),
) -> Any:
    """List all API tokens for the current tenant."""
    service = ApiTokenService(repo)
    tokens = await service.list_tokens(tenant_id)
    return ApiTokenListResponse(
        tokens=[ApiTokenListItem.model_validate(t, from_attributes=True) for t in tokens]
    )
