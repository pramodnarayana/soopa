"""Port protocol for outbound authentication strategies."""

from abc import abstractmethod
from typing import Protocol

import httpx


class AuthenticatorPort(Protocol):
    """Hexagonal outbound port for authenticating outgoing HTTP requests."""

    @abstractmethod
    def authenticate_request(self, request: httpx.Request) -> httpx.Request:
        """Injects authentication headers, query parameters, or client certs into a request."""
        ...

    @abstractmethod
    async def is_valid(self) -> bool:
        """Verifies if the current credentials/tokens are valid and unexpired."""
        ...

    @abstractmethod
    async def refresh_if_needed(self) -> bool:
        """Refreshes tokens if near expiration. Returns True if refresh occurred."""
        ...
