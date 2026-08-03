"""
FastAPI dependency for two-part API key (M2M) authentication.

ERP systems authenticate using a Client ID + Client Secret pair (Stripe/AWS style):
    X-Client-ID:     soopaedi_acme_a3f12b9c   (plaintext, safe to log)
    X-Client-Secret: <43-char random secret>  (hashed, never logged)

Validation:
  1. Look up the ApiToken row by client_id (fast plaintext index — O(1))
  2. SHA-256 hash the incoming secret
  3. Constant-time compare against stored secret_hash
  4. Return tenant_id

No external network call to Zitadel or any IdP is made.
"""

import hashlib
import hmac
import logging

from database.base_repository import GlobalSession
from database.session import get_global_session
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from api.adapters.api_token_repository import SqlAlchemyApiTokenRepository

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)

# In-process cache: { client_id → (tenant_id, secret_hash) }
# Short-circuits the DB lookup for repeated calls within the same process.
# Tokens are evicted on revocation via invalidate_token_cache().
_token_cache: dict[str, tuple[str, str]] = {}
_MAX_CACHE_SIZE = 5000


async def get_tenant_id_from_api_key(
    auth: HTTPAuthorizationCredentials | None = Security(_bearer_scheme),  # noqa: B008
    global_session: GlobalSession = Depends(get_global_session),  # noqa: B008
) -> str:
    """
    Resolves a single API Bearer token to a tenant_id.

    Expected header:
        Authorization: Bearer <client_id>_<client_secret>

    Raises HTTP 401 if the header is missing, the token is malformed,
    the client_id doesn't exist, or the secret doesn't match.
    """
    if not auth or not auth.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing credentials. Provide Authorization: Bearer <token>",
            headers={"WWW-Authenticate": "Bearer"},
        )

    parts = auth.credentials.rsplit("_", 1)
    if len(parts) != 2:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token format.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    client_id, client_secret = parts[0], parts[1]

    # Hash the secret before touching the DB (raw secret never persisted or logged)
    secret_hash = hashlib.sha256(client_secret.encode("utf-8")).hexdigest()

    # Fast path: cache hit (only safe because we evict on revocation)
    if client_id in _token_cache:
        cached_tenant_id, cached_secret_hash = _token_cache[client_id]
        if hmac.compare_digest(cached_secret_hash, secret_hash):
            return cached_tenant_id

    token_repo = SqlAlchemyApiTokenRepository(global_session)
    tenant_id = await token_repo.get_tenant_id_by_credentials(client_id, secret_hash)

    if tenant_id is None:
        logger.warning(f"API key authentication failed for client_id={client_id!r}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked credentials.",
            headers={"WWW-Authenticate": "X-API-Key"},
        )

    # Populate cache (bounded eviction)
    if len(_token_cache) >= _MAX_CACHE_SIZE:
        _token_cache.pop(next(iter(_token_cache)))
    _token_cache[client_id] = (tenant_id, secret_hash)

    return tenant_id


def invalidate_token_cache(client_id: str) -> None:
    """
    Remove a client_id from the in-process cache.
    Must be called after revoking a token so cached entries don't persist.
    """
    _token_cache.pop(client_id, None)
