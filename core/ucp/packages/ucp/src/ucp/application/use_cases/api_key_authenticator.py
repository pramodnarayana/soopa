from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from enum import StrEnum

import structlog
from identity.application.authenticate_use_case import AuthenticationError
from identity.domain.identity_context import M2M_API_KEY_PREFIX, IdentityContext
from identity.ports.outbound.api_token_repository_port import ApiTokenRepositoryPort

logger = structlog.get_logger(__name__)

_DUMMY_SHA256_HEX = "0" * 64
_M2M_ROLE = "m2m_api_client"


class ApiKeyAuthErrorCode(StrEnum):
    """Canonical authentication error codes for M2M API keys."""

    INVALID_PREFIX = "APIKEY_INVALID_PREFIX"
    INVALID_FORMAT = "APIKEY_INVALID_FORMAT"
    INVALID_OR_REVOKED = "APIKEY_INVALID_OR_REVOKED"


def _normalize_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def authenticate_api_key(
    token: str,
    token_repo: ApiTokenRepositoryPort,
    *,
    now: datetime | None = None,
) -> IdentityContext:
    """
    Validates an M2M API token against authoritative shared repository state
    and returns a Machine IdentityContext.

    Always verifies active status, expiration, and constant-time secret digest
    directly against shared storage so token revocation and deletion take effect
    immediately across all API replicas and worker processes.
    """
    if not token.startswith(M2M_API_KEY_PREFIX):
        raise AuthenticationError(ApiKeyAuthErrorCode.INVALID_PREFIX.value)

    stripped_token = token.removeprefix(M2M_API_KEY_PREFIX)
    parts = stripped_token.rsplit(".", 1)
    if len(parts) != 2:
        raise AuthenticationError(ApiKeyAuthErrorCode.INVALID_FORMAT.value)

    client_id, client_secret = parts[0], parts[1]
    secret_hash = hashlib.sha256(client_secret.encode("utf-8")).hexdigest()
    reference_now = _normalize_utc(now)

    token_record = await token_repo.get_by_client_id(client_id)
    candidate_hash = token_record.secret_hash if token_record is not None else _DUMMY_SHA256_HEX
    digest_matches = hmac.compare_digest(candidate_hash, secret_hash)
    is_valid_token = (
        token_record is not None
        and token_record.active
        and not token_record.is_expired(at=reference_now)
        and digest_matches
    )
    if not is_valid_token:
        logger.error("api_key_authentication_failed", client_id=client_id)
        raise AuthenticationError(ApiKeyAuthErrorCode.INVALID_OR_REVOKED.value)

    assert token_record is not None
    return _build_machine_identity(client_id, token_record.tenant_id)


def _build_machine_identity(client_id: str, tenant_id: str) -> IdentityContext:
    return IdentityContext(
        subject=f"machine_{client_id}",
        tenant_id=tenant_id,
        organization_id=None,
        authorized_tenants={tenant_id},
        roles=(_M2M_ROLE,),
        permissions=(),
        claims={"client_id": client_id, "is_m2m": True},
    )
