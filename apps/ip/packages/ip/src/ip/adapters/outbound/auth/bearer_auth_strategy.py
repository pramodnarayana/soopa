"""Bearer token authentication strategy."""

import httpx
from ip.ports.outbound.auth_strategy_port import AuthenticatorPort


class BearerAuthStrategy(AuthenticatorPort):
    """Injects token into an Authorization: Bearer <token> header."""

    def __init__(self, token: str) -> None:
        if not token.strip():
            raise ValueError("Bearer token cannot be empty.")
        self._token = token.strip()

    def authenticate_request(self, request: httpx.Request) -> httpx.Request:
        request.headers["Authorization"] = f"Bearer {self._token}"
        return request

    async def is_valid(self) -> bool:
        return bool(self._token)

    async def refresh_if_needed(self) -> bool:
        return False
