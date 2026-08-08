import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx
import jwt
from jwt import PyJWKClient

from identity.domain.identity_context import PLATFORM_TENANT_ID, TokenClaims
from identity.ports.token_verifier import TokenVerifier

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ZitadelTokenVerifierOptions:
    issuer: str
    audience: str | list[str]
    jwks_url: str | None = None
    platform_org_id: str | None = None


class ZitadelTokenVerifier(TokenVerifier):
    def __init__(self, options: ZitadelTokenVerifierOptions) -> None:
        self._options = options
        self._jwks_url = options.jwks_url or f"{options.issuer}/oauth/v2/keys"
        self._jwks_client = PyJWKClient(self._jwks_url)
        # Thread-safe async cache for userinfo to prevent network calls on every request
        # Format: {jti: (userinfo_dict, timestamp)}
        self._userinfo_cache: dict[str, tuple[dict[str, Any], float]] = {}

    async def verify(self, token: str) -> TokenClaims:
        signing_key = await self._get_signing_key(token)
        try:
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self._options.audience,
                issuer=self._options.issuer,
            )
        except Exception as e:
            logger.error("JWT decode failed", exc_info=e)
            raise

        # Fallback to /userinfo if roles are missing (with enterprise caching)
        if "urn:zitadel:iam:org:project:roles" not in payload:
            jti = payload.get("jti")
            if jti is None:
                # Hash token to derive cache key when jti is absent
                jti = hashlib.sha256(token.encode()).hexdigest()
            try:
                userinfo = await self._get_cached_userinfo(token, jti)
                payload.update(userinfo)
            except Exception as e:
                logger.warning("Failed to fetch userinfo", exc_info=e)

        # Adapter translation: map the actual Zitadel Platform Org ID to the domain's sentinel ID
        roles_dict = payload.get("urn:zitadel:iam:org:project:roles")
        if roles_dict and isinstance(roles_dict, dict) and self._options.platform_org_id:
            for _role, orgs in roles_dict.items():
                if isinstance(orgs, dict) and self._options.platform_org_id in orgs:
                    orgs[PLATFORM_TENANT_ID] = orgs[self._options.platform_org_id]

        return TokenClaims.model_validate(payload)

    async def _get_signing_key(self, token: str) -> Any:
        return await asyncio.to_thread(self._jwks_client.get_signing_key_from_jwt, token)

    async def _get_cached_userinfo(self, token: str, jti: str) -> dict[str, Any]:
        now = time.time()

        # Check TTL cache (O(1) access)
        if jti in self._userinfo_cache:
            userinfo, timestamp = self._userinfo_cache[jti]
            if now - timestamp < 3600:
                return userinfo
            else:
                del self._userinfo_cache[jti]

        # Fetch from Zitadel asynchronously (no thread pool exhaustion)
        url = f"{self._options.issuer}/oidc/v1/userinfo"
        headers = {"Authorization": f"Bearer {token}"}

        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            userinfo = response.json()

        # Update cache
        self._userinfo_cache[jti] = (userinfo, now)

        # O(1) eviction for maxsize
        if len(self._userinfo_cache) > 1000:
            # Dictionaries in Python 3.7+ maintain insertion order.
            # Delete the oldest key (the first one added)
            oldest_key = next(iter(self._userinfo_cache))
            del self._userinfo_cache[oldest_key]

        return userinfo
