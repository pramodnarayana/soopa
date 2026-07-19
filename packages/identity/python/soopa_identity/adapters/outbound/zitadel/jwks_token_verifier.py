from dataclasses import dataclass
from typing import Any

import httpx
import jwt
from jwt import PyJWKClient

from soopa_identity.domain.identity_context import TokenClaims
from soopa_identity.ports.token_verifier import TokenVerifier


@dataclass(frozen=True)
class ZitadelTokenVerifierOptions:
    issuer: str
    audience: str
    jwks_url: str | None = None


class ZitadelTokenVerifier(TokenVerifier):
    def __init__(self, options: ZitadelTokenVerifierOptions) -> None:
        self._options = options
        self._jwks_url = options.jwks_url or f"{options.issuer}/oauth/v2/keys"
        self._jwks_client = PyJWKClient(self._jwks_url)

    async def verify(self, token: str) -> TokenClaims:
        signing_key = await self._get_signing_key(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=self._options.audience,
            issuer=self._options.issuer,
        )
        return TokenClaims.model_validate(payload)

    async def _get_signing_key(self, token: str) -> Any:
        async with httpx.AsyncClient() as client:
            response = await client.get(self._jwks_url)
            response.raise_for_status()
        return self._jwks_client.get_signing_key_from_jwt(token)
