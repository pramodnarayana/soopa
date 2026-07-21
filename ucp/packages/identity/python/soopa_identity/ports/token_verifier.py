from typing import Protocol

from soopa_identity.domain.identity_context import TokenClaims


class TokenVerifier(Protocol):
    async def verify(self, token: str) -> TokenClaims:
        raise NotImplementedError
