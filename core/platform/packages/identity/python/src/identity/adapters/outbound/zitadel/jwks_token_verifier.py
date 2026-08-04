import asyncio
import hashlib
import logging
from dataclasses import dataclass
from typing import Any

import jwt
from jwt import PyJWKClient

from identity.domain.identity_context import TokenClaims, PLATFORM_TENANT_ID
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
        # Cache for userinfo to prevent network calls on every request: {jti: (userinfo_dict, timestamp)}
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
            for role, orgs in roles_dict.items():
                if isinstance(orgs, dict) and self._options.platform_org_id in orgs:
                    orgs[PLATFORM_TENANT_ID] = orgs[self._options.platform_org_id]

        return TokenClaims.model_validate(payload)

    async def _get_signing_key(self, token: str) -> Any:
        return await asyncio.to_thread(self._jwks_client.get_signing_key_from_jwt, token)

    async def _get_cached_userinfo(self, token: str, jti: str) -> dict[str, Any]:
        import json
        import time
        from urllib.request import Request, urlopen

        now = time.time()
        # Check cache (1 hour TTL)
        if jti in self._userinfo_cache:
            userinfo, timestamp = self._userinfo_cache[jti]
            if now - timestamp < 3600:
                return userinfo

        # Fetch from Zitadel if not cached or expired
        url = f"{self._options.issuer}/oidc/v1/userinfo"
        req = Request(url, headers={"Authorization": f"Bearer {token}"})

        def _fetch() -> dict[str, Any]:
            with urlopen(req, timeout=5) as response:
                return dict(json.loads(response.read().decode()))

        userinfo = await asyncio.to_thread(_fetch)

        # Update cache and prevent memory leaks
        self._userinfo_cache[jti] = (userinfo, now)
        if len(self._userinfo_cache) > 1000:
            # Simple cleanup: keep newest 500
            sorted_cache = sorted(self._userinfo_cache.items(), key=lambda x: x[1][1], reverse=True)
            self._userinfo_cache = dict(sorted_cache[:500])

        return userinfo
