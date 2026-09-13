from typing import Any

import httpx
import structlog

from identity.adapters.outbound.zitadel.exceptions import (
    HttpStatusCode,
    ZitadelHttpBadRequestError,
    ZitadelHttpConflictError,
    ZitadelHttpError,
    ZitadelHttpNotFoundError,
)
from identity.adapters.outbound.zitadel.machine_key_auth import ZitadelMachineTokenProvider

logger = structlog.get_logger(__name__)

ERROR_MAPPING: dict[int, type[ZitadelHttpError]] = {
    HttpStatusCode.CONFLICT.value: ZitadelHttpConflictError,
    HttpStatusCode.NOT_FOUND.value: ZitadelHttpNotFoundError,
    HttpStatusCode.BAD_REQUEST.value: ZitadelHttpBadRequestError,
}


class ZitadelClient:
    def __init__(
        self,
        api_url: str,
        machine_key: str,
        ucp_project_id: str | None = None,
        default_user_password: str | None = None,
    ) -> None:
        self.api_url = api_url
        self.machine_key = machine_key
        self.ucp_project_id = ucp_project_id
        self.default_user_password = default_user_password
        self._client: httpx.AsyncClient | None = None
        self._token_provider: ZitadelMachineTokenProvider | None = None

    def _assert_config(self) -> None:
        if not self.machine_key:
            raise ValueError("ZITADEL_MACHINE_KEY is not configured")
        if not self.api_url.startswith("https://"):
            raise ValueError("ZITADEL_API_URL must use HTTPS scheme")

    def _get_client(self) -> httpx.AsyncClient:
        """Get or create a persistent AsyncClient with timeout configuration."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(30.0))
        return self._client

    async def close(self) -> None:
        """Close the persistent client connection."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def fetch_with_auth(
        self,
        endpoint: str,
        method: str = "GET",
        json: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        self._assert_config()

        client = self._get_client()
        if self._token_provider is None:
            self._token_provider = ZitadelMachineTokenProvider(self.api_url, self.machine_key)

        access_token = await self._token_provider.get_access_token(client)
        req_headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }
        if headers:
            req_headers.update(headers)

        url = f"{self.api_url}{endpoint}"
        response = await client.request(method, url, headers=req_headers, json=json)

        if response.status_code >= 400:
            error_text = response.text
            ExceptionClass = ERROR_MAPPING.get(response.status_code, ZitadelHttpError)

            logger.error(
                "zitadel_http_request_failed",
                endpoint=endpoint,
                status_code=response.status_code,
                error_text=error_text,
            )

            raise ExceptionClass(
                message=f"Request to {endpoint} failed with {response.status_code}: {error_text}",
                status_code=response.status_code,
                original_error=Exception(error_text),
            )

        return response
