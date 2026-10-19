"""No-authentication strategy for public or network-isolated endpoints."""

import httpx
from ip.ports.outbound.auth_strategy_port import AuthenticatorPort


class NoAuthStrategy(AuthenticatorPort):
    """Pass-through strategy that performs no modification on outgoing requests."""

    def authenticate_request(self, request: httpx.Request) -> httpx.Request:
        return request

    async def is_valid(self) -> bool:
        return True

    async def refresh_if_needed(self) -> bool:
        return False
