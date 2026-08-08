import hashlib
import os
import secrets

from identity.domain.identity_context import M2M_API_KEY_PREFIX
from platform_orm.models.identity import ApiToken

from ucp.adapters.inbound.http.dtos.api_token_dtos import (
    ApiTokenCreatedResponse,
    CreateApiTokenRequest,
    UpdateApiTokenRequest,
)
from ucp.ports.api_token_repository import ApiTokenRepositoryPort


class ApiTokenService:
    def __init__(self, token_repo: ApiTokenRepositoryPort):
        self.token_repo = token_repo

    async def list_tokens(self, tenant_id: str) -> list[ApiToken]:
        return await self.token_repo.get_all_by_tenant(tenant_id)

    async def get_token(self, token_id: str, tenant_id: str) -> ApiToken | None:
        return await self.token_repo.get_by_id(token_id, tenant_id)

    async def create_token(
        self, tenant_id: str, request: CreateApiTokenRequest
    ) -> ApiTokenCreatedResponse:
        # Generate raw secrets
        client_id = f"cli_{secrets.token_hex(16)}"
        secret = f"sec_{secrets.token_urlsafe(32)}"

        # Hash the secret (SHA-256)
        secret_hash = hashlib.sha256(secret.encode()).hexdigest()

        token_model = ApiToken(
            id=f"{ApiToken.ID_PREFIX}_{os.urandom(12).hex()}",
            tenant_id=tenant_id,
            name=request.name,
            client_id=client_id,
            secret_hash=secret_hash,
            expires_at=request.expires_at,
            active=True,
        )

        created_token = await self.token_repo.create(token_model)

        # Return the created token with the combined string (client_id.secret)
        # The frontend will display this single string to the developer.
        # The backend auth middleware will split it by '.' to perform O(1) lookups.
        return ApiTokenCreatedResponse(
            id=created_token.id,
            name=created_token.name,
            client_id=created_token.client_id,
            active=created_token.active,
            last_used_at=created_token.last_used_at,
            expires_at=created_token.expires_at,
            created_at=created_token.created_at,
            token=f"{M2M_API_KEY_PREFIX}{client_id}.{secret}",
        )

    async def update_token(
        self, token_id: str, tenant_id: str, request: UpdateApiTokenRequest
    ) -> ApiToken | None:
        from typing import Any

        update_data: dict[str, Any] = {}
        if request.name is not None:
            update_data["name"] = request.name
        if request.active is not None:
            update_data["active"] = request.active

        return await self.token_repo.update(token_id, tenant_id, **update_data)

    async def delete_token(self, token_id: str, tenant_id: str) -> bool:
        return await self.token_repo.delete(token_id, tenant_id)
