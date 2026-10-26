from collections.abc import Sequence

import httpx
from ip.engine.ports.outbound.auth_strategy_port import AuthenticatorPort


class NoAuthStrategy(AuthenticatorPort):
    """Pass-through strategy that performs no modification on outgoing requests."""

    @property
    def sensitive_header_names(self) -> Sequence[str]:
        return ()

    def authenticate_request(self, request: httpx.Request) -> httpx.Request:
        return request

    async def is_valid(self) -> bool:
        return True

    async def refresh_if_needed(self) -> bool:
        return False
