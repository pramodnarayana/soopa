"""
Core service for managing platform API tokens (M2M authentication).

Follows Hexagonal Architecture:
  - Depends on ApiTokenRepositoryPort (port), never on SQLAlchemy.
  - Pure Python: testable without a DB or framework.

Two-part credential pattern (Stripe/AWS style):
  - client_id:     stored plaintext, visible in UI, used for fast indexed lookup.
  - client_secret: only SHA-256 hash stored; raw value shown once and discarded.
"""

import hashlib
import logging
import secrets
from uuid import UUID

from api.auth.api_key import invalidate_token_cache
from api.domain.models import ApiTokenEntity, ApiTokenListEntity, CreateApiTokenCmd
from api.ports.repository import ApiTokenRepositoryPort

logger = logging.getLogger(__name__)

_TOKEN_VENDOR = "soopaedi"


def _generate_credentials(tenant_name: str) -> tuple[str, str, str]:
    """
    Pure function — no I/O, deterministically testable.

    Returns (client_id, client_secret, secret_hash).

    client_id format:    soopaedi_<6-char-slug>_<8-hex-chars>
                         e.g. soopaedi_acmeco_a3f12b9c
    client_secret format: 43-char URL-safe random string (32 random bytes)

    Only secret_hash is stored. client_id is stored in plaintext.
    """
    slug = "".join(c for c in tenant_name.lower() if c.isalnum())[:6]
    random_suffix = secrets.token_hex(4)  # 8 hex chars
    client_id = f"{_TOKEN_VENDOR}_{slug}_{random_suffix}"

    client_secret = secrets.token_urlsafe(32)  # 43 URL-safe chars
    secret_hash = hashlib.sha256(client_secret.encode("utf-8")).hexdigest()

    return client_id, client_secret, secret_hash


class ApiTokenService:
    """
    Application service responsible for the lifecycle of tenant API tokens.

    Constructor receives ApiTokenRepositoryPort — a pure interface.
    No framework, no DB, no network dependency at construction time.
    """

    def __init__(self, repo: ApiTokenRepositoryPort) -> None:
        self._repo = repo

    async def create_token(
        self, tenant_id: str, tenant_name: str, cmd: CreateApiTokenCmd
    ) -> ApiTokenEntity:
        """
        Generates a two-part API credential for the given tenant.
        client_secret is returned exactly once and is NOT stored.
        """
        client_id, client_secret, secret_hash = _generate_credentials(tenant_name)

        token_id = await self._repo.create_api_token(
            tenant_id=tenant_id,
            name=cmd.name,
            client_id=client_id,
            secret_hash=secret_hash,
            expires_at=cmd.expires_at,
        )

        logger.info(
            "API token created",
            extra={"tenant_id": tenant_id, "token_name": cmd.name, "client_id": client_id},
        )

        return ApiTokenEntity(
            id=token_id,
            tenant_id=tenant_id,
            name=cmd.name,
            client_id=client_id,
            client_secret=client_secret,  # caller must show this exactly once
            active=False,
        )

    async def list_tokens(self, tenant_id: str) -> list[ApiTokenListEntity]:
        """Returns all tokens for a tenant. client_id is safe; secret is never returned."""
        return await self._repo.list_api_tokens(tenant_id)

    async def update_token(
        self, tenant_id: str, token_id: UUID, name: str | None = None, active: bool | None = None
    ) -> bool:
        """Updates token properties (e.g. name or active status)."""
        token = await self._repo.get_api_token(tenant_id, token_id)
        if not token:
            return False

        result = await self._repo.update_api_token(tenant_id, token_id, name, active)
        if result:
            # If the token is being deactivated, invalidate the cache
            if active is False:
                invalidate_token_cache(token["client_id"])

            logger.info(
                "API token updated", extra={"tenant_id": tenant_id, "token_id": str(token_id)}
            )
        return result

    async def delete_token(self, tenant_id: str, token_id: UUID) -> bool:
        """Hard deletes a token record. Irreversible."""
        token = await self._repo.get_api_token(tenant_id, token_id)
        if not token:
            return False

        result = await self._repo.delete_api_token(tenant_id, token_id)
        if result:
            invalidate_token_cache(token["client_id"])
            logger.info(
                "API token deleted", extra={"tenant_id": tenant_id, "token_id": str(token_id)}
            )
        return result
