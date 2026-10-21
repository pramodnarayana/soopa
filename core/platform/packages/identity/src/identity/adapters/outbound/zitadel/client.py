from __future__ import annotations

import httpx
import structlog
from seedwork.domain.types import JsonDict
from shttp import HttpClient, HttpError, create_http_client

from identity.adapters.outbound.zitadel.exceptions import ZitadelHttpError
from identity.adapters.outbound.zitadel.machine_key_auth import ZitadelMachineTokenProvider

logger = structlog.get_logger(__name__)


class ZitadelClient:
    def __init__(
        self,
        api_url: str,
        machine_key: str,
        ucp_project_id: str | None = None,
        default_user_password: str | None = None,
        platform_org_id: str | None = None,
        client: HttpClient | None = None,
    ) -> None:
        self.api_url = api_url
        self.machine_key = machine_key
        self.ucp_project_id = ucp_project_id
        self.default_user_password = default_user_password
        self.platform_org_id = platform_org_id
        self._client: HttpClient = client or HttpClient(
            create_http_client(timeout=httpx.Timeout(30.0, connect=10.0)),
            allow_private_ips=True,
        )
        self._token_provider: ZitadelMachineTokenProvider | None = None

    def _assert_config(self) -> None:
        if not self.machine_key:
            raise ValueError("IDENTITY_MACHINE_KEY is not configured")
        if not self.api_url.startswith("https://") and not self.api_url.startswith("http://"):
            raise ValueError("IDENTITY_API_URL must use HTTP or HTTPS scheme")

    def _get_client(self) -> HttpClient:
        """Get the underlying HttpClient."""
        return self._client

    @property
    def raw_client(self) -> httpx.AsyncClient:
        """Get the underlying httpx.AsyncClient if needed."""
        return self._client.raw_client

    async def close(self) -> None:
        """Close the persistent client connection."""
        await self._client.close()

    async def fetch_with_auth(
        self,
        endpoint: str,
        method: str = "GET",
        json: JsonDict | None = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        self._assert_config()

        if self._token_provider is None:
            self._token_provider = ZitadelMachineTokenProvider(self.api_url, self.machine_key)

        access_token = await self._token_provider.get_access_token(self._client)
        req_headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }
        if headers:
            req_headers.update(headers)

        url = f"{self.api_url}{endpoint}"
        try:
            response = await self._client.request(
                method=method,
                url=url,
                headers=req_headers,
                json=json,
                allow_private_ips=True,
            )
        except HttpError as exc:
            logger.error(
                "zitadel_http_request_exception",
                endpoint=endpoint,
                error=str(exc),
            )
            raise ZitadelHttpError(
                message=f"Request to {endpoint} failed: {exc}",
                status_code=500,
                original_error=exc,
            ) from exc

        return response
