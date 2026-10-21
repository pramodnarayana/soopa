"""HTTP Basic Authentication strategy."""

import base64

import httpx
from ip.ports.outbound.auth_strategy_port import AuthenticatorPort


class BasicAuthStrategy(AuthenticatorPort):
    """Encodes username:password into an Authorization: Basic <encoded> header."""

    def __init__(self, username: str, password: str) -> None:
        if not username:
            raise ValueError("Basic auth username cannot be empty.")
        self._username = username
        self._password = password
        raw = f"{self._username}:{self._password}"
        self._encoded = base64.b64encode(raw.encode("utf-8")).decode("ascii")

    def authenticate_request(self, request: httpx.Request) -> httpx.Request:
        request.headers["Authorization"] = f"Basic {self._encoded}"
        return request

    async def is_valid(self) -> bool:
        return bool(self._username and self._password)

    async def refresh_if_needed(self) -> bool:
        return False
