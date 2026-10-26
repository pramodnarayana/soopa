from collections.abc import Sequence

import httpx
from ip.engine.domain.enums import ApiKeyPlacement
from ip.engine.domain.exceptions import InvalidCredentialsError
from ip.engine.ports.outbound.auth_strategy_port import AuthenticatorPort


class ApiKeyAuthStrategy(AuthenticatorPort):
    """Injects an API key into an HTTP header or query parameter."""

    def __init__(
        self,
        api_key: str,
        param_name: str = "X-API-Key",
        placement: ApiKeyPlacement = ApiKeyPlacement.HEADER,
    ) -> None:
        self._api_key = api_key.strip()
        self._param_name = param_name.strip()
        self._placement = placement

    @property
    def param_name(self) -> str:
        return self._param_name

    @property
    def placement(self) -> ApiKeyPlacement:
        return self._placement

    @property
    def sensitive_header_names(self) -> Sequence[str]:
        return (self._param_name,) if self._placement == ApiKeyPlacement.HEADER else ()

    def validate(self) -> InvalidCredentialsError | None:
        if not self._api_key:
            return InvalidCredentialsError(
                field_name="api_key",
                message="API key cannot be empty.",
            )
        if not self._param_name:
            return InvalidCredentialsError(
                field_name="param_name",
                message="Parameter name cannot be empty.",
            )
        return None

    def authenticate_request(self, request: httpx.Request) -> httpx.Request:
        if self.validate() is not None:
            return request
        if self._placement == ApiKeyPlacement.HEADER:
            request.headers[self._param_name] = self._api_key
        else:
            request.url = request.url.copy_set_param(self._param_name, self._api_key)
        return request

    async def is_valid(self) -> bool:
        return self.validate() is None

    async def refresh_if_needed(self) -> bool:
        return False


__all__ = ["ApiKeyAuthStrategy", "ApiKeyPlacement"]
