"""HTTP authentication protocols for the centralized platform HTTP package."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol

import httpx

if TYPE_CHECKING:
    from .client import HttpClient


class BearerTokenProvider(Protocol):
    """Protocol for asynchronous OAuth2 / M2M Bearer token providers."""

    async def get_access_token(self, client: HttpClient) -> str: ...


class HttpRequestAuthenticator(Protocol):
    """Protocol for authenticating outgoing HTTP requests (headers, query params, token refresh)."""

    @property
    def sensitive_header_names(self) -> Sequence[str]:
        """Header names injected by this authenticator that carry sensitive credentials."""
        ...

    def authenticate_request(self, request: httpx.Request) -> httpx.Request:
        """Injects authentication headers or query parameters into an outgoing request."""
        ...

    async def is_valid(self) -> bool:
        """Verifies whether the current credentials or tokens are valid and unexpired."""
        ...

    async def refresh_if_needed(self) -> bool:
        """Refreshes tokens if near expiration. Returns True if refresh occurred."""
        ...


__all__ = ["BearerTokenProvider", "HttpRequestAuthenticator"]
