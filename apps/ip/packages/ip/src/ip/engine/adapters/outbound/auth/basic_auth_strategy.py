import base64
from collections.abc import Sequence

import httpx
from ip.engine.domain.exceptions import InvalidCredentialsError
from ip.engine.ports.outbound.auth_strategy_port import AuthenticatorPort


class BasicAuthStrategy(AuthenticatorPort):
    """Encodes username:password into an Authorization: Basic <encoded> header."""

    def __init__(self, username: str, password: str) -> None:
        self._username = username
        self._password = password
        raw = f"{self._username}:{self._password}"
        self._encoded = base64.b64encode(raw.encode("utf-8")).decode("ascii")

    @property
    def sensitive_header_names(self) -> Sequence[str]:
        return ("Authorization",)

    def validate(self) -> InvalidCredentialsError | None:
        if not self._username:
            return InvalidCredentialsError(
                field_name="username",
                message="Basic auth username cannot be empty.",
            )
        return None

    def authenticate_request(self, request: httpx.Request) -> httpx.Request:
        if self.validate() is None:
            request.headers["Authorization"] = f"Basic {self._encoded}"
        return request

    async def is_valid(self) -> bool:
        return self.validate() is None

    async def refresh_if_needed(self) -> bool:
        return False
