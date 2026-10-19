"""OAuth 2.0 authentication strategy with automatic token refresh."""

from collections.abc import Callable
from datetime import UTC, datetime

import httpx
from ip.ports.outbound.auth_strategy_port import AuthenticatorPort


class OAuth2Strategy(AuthenticatorPort):
    """Handles OAuth 2.0 bearer authorization and token renewal."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        token_url: str,
        access_token: str,
        refresh_token: str | None = None,
        expires_at_epoch: float | None = None,
        on_token_refreshed: Callable[[str, str | None, float | None], None] | None = None,
        refresh_buffer_seconds: int = 120,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._token_url = token_url
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._expires_at_epoch = expires_at_epoch
        self._on_token_refreshed = on_token_refreshed
        self._refresh_buffer_seconds = refresh_buffer_seconds

    @property
    def access_token(self) -> str:
        return self._access_token

    @property
    def refresh_token(self) -> str | None:
        return self._refresh_token

    def authenticate_request(self, request: httpx.Request) -> httpx.Request:
        request.headers["Authorization"] = f"Bearer {self._access_token}"
        return request

    async def is_valid(self) -> bool:
        if not self._access_token:
            return False
        if self._expires_at_epoch is None:
            return True
        now = datetime.now(UTC).timestamp()
        return now < (self._expires_at_epoch - self._refresh_buffer_seconds)

    async def refresh_if_needed(self) -> bool:
        """Refreshes the token if expired or nearing expiration."""
        if await self.is_valid():
            return False

        if not self._refresh_token:
            return False

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                self._token_url,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self._refresh_token,
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
            )
            resp.raise_for_status()
            payload = resp.json()

        new_access_token = payload.get("access_token")
        if not new_access_token:
            raise ValueError("Token response did not include access_token")

        new_refresh_token = payload.get("refresh_token") or self._refresh_token
        expires_in = payload.get("expires_in")
        new_expires_epoch = (
            datetime.now(UTC).timestamp() + float(expires_in) if expires_in is not None else None
        )

        self._access_token = str(new_access_token)
        self._refresh_token = str(new_refresh_token) if new_refresh_token else None
        self._expires_at_epoch = new_expires_epoch

        if self._on_token_refreshed:
            self._on_token_refreshed(
                self._access_token, self._refresh_token, self._expires_at_epoch
            )

        return True
