"""API Key authentication strategy (header or query parameter)."""

from enum import StrEnum

import httpx
from ip.ports.outbound.auth_strategy_port import AuthenticatorPort


class ApiKeyPlacement(StrEnum):
    HEADER = "HEADER"
    QUERY_PARAM = "QUERY_PARAM"


class ApiKeyAuthStrategy(AuthenticatorPort):
    """Injects an API key into an HTTP header or query parameter."""

    def __init__(
        self,
        api_key: str,
        param_name: str = "X-API-Key",
        placement: ApiKeyPlacement = ApiKeyPlacement.HEADER,
    ) -> None:
        if not api_key.strip():
            raise ValueError("API key cannot be empty.")
        if not param_name.strip():
            raise ValueError("Parameter name cannot be empty.")
        self._api_key = api_key.strip()
        self._param_name = param_name.strip()
        self._placement = placement

    def authenticate_request(self, request: httpx.Request) -> httpx.Request:
        if self._placement == ApiKeyPlacement.HEADER:
            request.headers[self._param_name] = self._api_key
        else:
            # Query parameter injection
            url = request.url.copy_with(
                params={**request.url.params, self._param_name: self._api_key}
            )
            request.url = url
        return request

    async def is_valid(self) -> bool:
        return bool(self._api_key)

    async def refresh_if_needed(self) -> bool:
        return False
