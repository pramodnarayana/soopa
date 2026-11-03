from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime

import structlog
from identity.domain.api_token import ApiToken
from identity.domain.identity_context import (
    M2M_API_KEY_PREFIX,
    M2M_CLIENT_ID_PREFIX,
    M2M_CLIENT_SECRET_PREFIX,
)
from seedwork.domain.exceptions import Result

from ucp.application.responses import ApiTokenCreatedResponse
from ucp.application.use_cases._identity_error_translator import translate_identity_error
from ucp.domain.exceptions import UcpError
from ucp.ports.outbound.uow_port import UcpUnitOfWorkPort

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class CreateApiTokenCommand:
    name: str
    expires_at: datetime | None = None


class CreateApiTokenUseCase:
    def __init__(self, uow: UcpUnitOfWorkPort) -> None:
        self.uow = uow

    async def execute(
        self, tenant_id: str, command: CreateApiTokenCommand
    ) -> Result[ApiTokenCreatedResponse, UcpError]:
        bound_logger = logger.bind(tenant_id=tenant_id, token_name=command.name)
        bound_logger.info("api_token_creation.started")

        client_id = f"{M2M_CLIENT_ID_PREFIX}{secrets.token_hex(16)}"
        secret = f"{M2M_CLIENT_SECRET_PREFIX}{secrets.token_urlsafe(32)}"
        secret_hash = hashlib.sha256(secret.encode()).hexdigest()

        create_res = ApiToken.create(
            tenant_id=tenant_id,
            name=command.name,
            client_id=client_id,
            secret_hash=secret_hash,
            expires_at=command.expires_at,
        )
        if create_res.is_err:
            err = create_res.unwrap_err()
            bound_logger.error(
                "api_token_creation.validation_failed",
                code=err.code.value,
                reason=err.message,
            )
            return Result.fail(translate_identity_error(err))

        token_model = create_res.unwrap()

        async with self.uow:
            created_token = await self.uow.api_token_repo.save(token_model)
            await self.uow.commit()

        bound_logger.info(
            "api_token_creation.completed",
            token_id=created_token.id,
            client_id=created_token.client_id,
        )
        return Result.ok(
            ApiTokenCreatedResponse(
                id=created_token.id,
                name=created_token.name,
                client_id=created_token.client_id,
                active=created_token.active,
                last_used_at=created_token.last_used_at,
                expires_at=created_token.expires_at,
                created_at=created_token.created_at,
                token=f"{M2M_API_KEY_PREFIX}{client_id}.{secret}",
            )
        )
