from collections.abc import Sequence

import httpx
from ip.engine.domain.exceptions import InvalidCredentialsError
from ip.engine.ports.outbound.auth_strategy_port import AuthenticatorPort


class BearerAuthStrategy(AuthenticatorPort):
    """Injects token into an Authorization: Bearer <token> header."""

    def __init__(self, token: str) -> None:
        self._token = token.strip()

    @property
    def sensitive_header_names(self) -> Sequence[str]:
        return ("Authorization",)

    def validate(self) -> InvalidCredentialsError | None:
        if not self._token:
            return InvalidCredentialsError(
                field_name="token",
                message="Bearer token cannot be empty.",
            )
        return None

    def authenticate_request(self, request: httpx.Request) -> httpx.Request:
        if self._token:
            request.headers["Authorization"] = f"Bearer {self._token}"
        return request

    async def is_valid(self) -> bool:
        return self.validate() is None

    async def refresh_if_needed(self) -> bool:
        return False
