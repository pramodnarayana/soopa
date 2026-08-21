import hashlib
import os
import secrets
from datetime import UTC, datetime

from identity.domain.identity_context import M2M_API_KEY_PREFIX

from ucp.domain.models.api_token import ApiTokenDomainModel
from ucp.domain.models.api_token_models import ApiTokenCreatedResult, CreateApiTokenCommand
from ucp.ports.outbound.uow_port import UcpUnitOfWorkPort


class CreateApiTokenUseCase:
    def __init__(self, uow: UcpUnitOfWorkPort):
        self.uow = uow

    async def execute(
        self, tenant_id: str, command: CreateApiTokenCommand
    ) -> ApiTokenCreatedResult:
        # Generate raw secrets
        client_id = f"cli_{secrets.token_hex(16)}"
        secret = f"sec_{secrets.token_urlsafe(32)}"

        # Hash the secret (SHA-256)
        secret_hash = hashlib.sha256(secret.encode()).hexdigest()

        async with self.uow:
            token_model = ApiTokenDomainModel(
                id=f"tok_{os.urandom(12).hex()}",
                tenant_id=tenant_id,
                name=command.name,
                client_id=client_id,
                secret_hash=secret_hash,
                last_used_at=None,
                expires_at=command.expires_at,
                active=True,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )

            created_token = await self.uow.api_token_repo.create(token_model)
            await self.uow.commit()

        # Return the created token with the combined string (client_id.secret)
        # The frontend will display this single string to the developer.
        # The backend auth middleware will split it by '.' to perform O(1) lookups.
        return ApiTokenCreatedResult(
            id=created_token.id,
            name=created_token.name,
            client_id=created_token.client_id,
            active=created_token.active,
            last_used_at=created_token.last_used_at,
            expires_at=created_token.expires_at,
            created_at=created_token.created_at,
            token=f"{M2M_API_KEY_PREFIX}{client_id}.{secret}",
        )
