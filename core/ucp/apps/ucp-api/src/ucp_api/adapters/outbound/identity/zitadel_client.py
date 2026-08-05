import logging
from typing import Any

import httpx
from ucp_api.core.config import get_settings
from ucp_api.core.exceptions import IdentityProviderError

logger = logging.getLogger(__name__)


class ZitadelClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.api_url = self.settings.zitadel_api_url
        self.token = self.settings.zitadel_api_token
        self.ucp_project_id = self.settings.zitadel_ucp_project_id
        # We can add default user password to config if needed, or rely on env
        self.default_user_password = "Password1!"
        self._client: httpx.AsyncClient | None = None

    def _assert_config(self) -> None:
        if not self.token:
            raise ValueError("ZITADEL_API_TOKEN is not configured")
        if not self.ucp_project_id:
            raise ValueError("ZITADEL_UCP_PROJECT_ID is not configured")

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

        req_headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        if headers:
            req_headers.update(headers)

        client = self._get_client()
        url = f"{self.api_url}{endpoint}"
        response = await client.request(method, url, headers=req_headers, json=json)
        return response

    async def handle_response_error(self, response: httpx.Response, action_context: str) -> None:
        error_text = response.text
        logger.error(f"Failed to {action_context}: {error_text}")
        raise IdentityProviderError(
            message=f"Failed to {action_context}", original_error=error_text
        )
