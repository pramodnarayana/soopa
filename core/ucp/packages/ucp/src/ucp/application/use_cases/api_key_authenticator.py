import hashlib
import hmac

import structlog
from fastapi import HTTPException, status
from identity.domain.identity_context import M2M_API_KEY_PREFIX, IdentityContext
from identity.ports.outbound.api_token_repository_port import ApiTokenRepositoryPort

logger = structlog.get_logger(__name__)

# In-process cache: { client_id → (tenant_id, secret_hash) }
# Short-circuits the DB lookup for repeated calls within the same process.
_token_cache: dict[str, tuple[str, str]] = {}
_MAX_CACHE_SIZE = 5000


async def authenticate_api_key(
    token: str,
    token_repo: ApiTokenRepositoryPort,
) -> IdentityContext:
    """
    Validates an M2M API token and returns a Machine IdentityContext.
    """
    if not token.startswith(M2M_API_KEY_PREFIX):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="APIKEY_INVALID_PREFIX",
            headers={"WWW-Authenticate": "Bearer"},
        )

    stripped_token = token.removeprefix(M2M_API_KEY_PREFIX)
    parts = stripped_token.rsplit(".", 1)
    if len(parts) != 2:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="APIKEY_INVALID_FORMAT",
            headers={"WWW-Authenticate": "Bearer"},
        )

    client_id, client_secret = parts[0], parts[1]
    secret_hash = hashlib.sha256(client_secret.encode("utf-8")).hexdigest()

    # Cache hit
    if client_id in _token_cache:
        cached_tenant_id, cached_secret_hash = _token_cache[client_id]
        if hmac.compare_digest(cached_secret_hash, secret_hash):
            return _build_machine_identity(client_id, cached_tenant_id)

    # DB Lookup (constant-time verification)
    token_record = await token_repo.get_by_client_id(client_id)
    if not token_record or not hmac.compare_digest(token_record.secret_hash, secret_hash):
        logger.warning(
            "API key authentication failed for client_id={client_id}", client_id=client_id
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="APIKEY_INVALID_OR_REVOKED",
            headers={"WWW-Authenticate": "Bearer"},
        )

    tenant_id = token_record.tenant_id

    # Populate cache
    if len(_token_cache) >= _MAX_CACHE_SIZE:
        _token_cache.pop(next(iter(_token_cache)))
    _token_cache[client_id] = (tenant_id, secret_hash)

    return _build_machine_identity(client_id, tenant_id)


def _build_machine_identity(client_id: str, tenant_id: str) -> IdentityContext:
    return IdentityContext(
        subject=f"machine_{client_id}",
        tenant_id=tenant_id,
        organization_id=None,
        authorized_tenants={tenant_id},
        roles=("m2m_api_client",),
        permissions=(),
        claims={"client_id": client_id, "is_m2m": True},
    )


def invalidate_api_key_cache(client_id: str) -> None:
    _token_cache.pop(client_id, None)
