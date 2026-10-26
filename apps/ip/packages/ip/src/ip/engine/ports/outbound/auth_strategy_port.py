from collections.abc import Sequence
from typing import Protocol

import httpx


class AuthenticatorPort(Protocol):
    """Hexagonal outbound port for authenticating outgoing HTTP requests."""

    @property
    def sensitive_header_names(self) -> Sequence[str]:
        """Header names injected by this authenticator that carry sensitive credentials."""
        ...

    def authenticate_request(self, request: httpx.Request) -> httpx.Request:
        """Injects authentication headers, query parameters, or client certs into a request."""
        ...

    async def is_valid(self) -> bool:
        """Verifies if the current credentials/tokens are valid and unexpired."""
        ...

    async def refresh_if_needed(self) -> bool:
        """Refreshes tokens if near expiration. Returns True if refresh occurred."""
        ...
