from typing import Protocol

from identity.domain.identity_context import TokenClaims


class TokenValidationError(Exception):
    """Raised when a token is mathematically invalid (e.g. expired or invalid signature)."""


class TokenVerifier(Protocol):
    async def verify(self, token: str) -> TokenClaims:
        raise NotImplementedError
