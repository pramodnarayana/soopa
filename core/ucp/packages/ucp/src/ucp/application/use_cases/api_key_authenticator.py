from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

import structlog
from identity.application.authenticate_use_case import AuthenticationError
from identity.domain.identity_context import M2M_API_KEY_PREFIX, IdentityContext
from identity.ports.outbound.api_token_repository_port import ApiTokenRepositoryPort

logger = structlog.get_logger(__name__)

_DUMMY_SHA256_HEX = "0" * 64
_MAX_CACHE_SIZE = 5000
_M2M_ROLE = "m2m_api_client"


class ApiKeyAuthErrorCode(StrEnum):
    """Canonical authentication error codes for M2M API keys."""

    INVALID_PREFIX = "APIKEY_INVALID_PREFIX"
    INVALID_FORMAT = "APIKEY_INVALID_FORMAT"
    INVALID_OR_REVOKED = "APIKEY_INVALID_OR_REVOKED"


@dataclass(frozen=True)
class _CachedApiTokenEntry:
    tenant_id: str
    secret_hash: str
    expires_at: datetime | None

    def is_expired(self, *, at: datetime) -> bool:
        if self.expires_at is None:
            return False
        normalized_expiry = (
            self.expires_at
            if self.expires_at.tzinfo is not None
            else self.expires_at.replace(tzinfo=UTC)
        )
        return at >= normalized_expiry.astimezone(UTC)


def _normalize_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


# In-process cache: { client_id -> _CachedApiTokenEntry }
# Short-circuits the DB lookup for repeated calls within the same process.
_token_cache: dict[str, _CachedApiTokenEntry] = {}


async def authenticate_api_key(
    token: str,
    token_repo: ApiTokenRepositoryPort,
    *,
    now: datetime | None = None,
) -> IdentityContext:
    """
    Validates an M2M API token and returns a Machine IdentityContext.
    Enforces secret digest verification and expiration on both cache-hit and database paths.
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

    # Cache hit: enforce expiration before returning cached machine identity
    cached_entry = _token_cache.get(client_id)
    if cached_entry is not None:
        if cached_entry.is_expired(at=reference_now):
            _token_cache.pop(client_id, None)
        elif hmac.compare_digest(cached_entry.secret_hash, secret_hash):
            return _build_machine_identity(client_id, cached_entry.tenant_id)

    # DB Lookup (constant-time digest verification on every lookup)
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
        _token_cache.pop(client_id, None)
        logger.error("api_key_authentication_failed", client_id=client_id)
        raise AuthenticationError(ApiKeyAuthErrorCode.INVALID_OR_REVOKED.value)

    assert token_record is not None
    tenant_id = token_record.tenant_id

    # Populate bounded cache with expiration metadata
    if len(_token_cache) >= _MAX_CACHE_SIZE and client_id not in _token_cache:
        _token_cache.pop(next(iter(_token_cache)))
    _token_cache[client_id] = _CachedApiTokenEntry(
        tenant_id=tenant_id,
        secret_hash=secret_hash,
        expires_at=token_record.expires_at,
    )

    return _build_machine_identity(client_id, tenant_id)


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


def invalidate_api_key_cache(client_id: str) -> None:
    _token_cache.pop(client_id, None)
