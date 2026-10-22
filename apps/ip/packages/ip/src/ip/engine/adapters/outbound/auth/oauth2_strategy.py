import asyncio
import inspect
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import httpx
import structlog
from ip.engine.domain.exceptions import (
    EndpointSecurityViolationError,
    InvalidCredentialsError,
)
from ip.engine.ports.outbound.auth_strategy_port import AuthenticatorPort
from shttp import HttpClient, HttpError, PassThroughPolicy, create_http_client
from shttp.exceptions import SsrfSecurityError
from shttp.resilience import HttpBackoffHandler

logger = structlog.get_logger(__name__)

TokenRefreshCallback = Callable[[str, str | None, float | None], Awaitable[None] | None]


class OAuth2Strategy(AuthenticatorPort):
    """Handles OAuth 2.0 bearer authorization and token renewal via centralized shttp.HttpClient."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        token_url: str,
        access_token: str,
        refresh_token: str | None = None,
        expires_at_epoch: float | None = None,
        on_token_refreshed: TokenRefreshCallback | None = None,
        refresh_buffer_seconds: int = 900,
        http_client: HttpClient | None = None,
        allow_private_ips: bool = False,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._token_url = token_url
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._expires_at_epoch = expires_at_epoch
        self._on_token_refreshed = on_token_refreshed
        self._refresh_buffer_seconds = refresh_buffer_seconds
        self._allow_private_ips = allow_private_ips
        self._http_client = http_client or HttpClient(
            client=create_http_client(timeout=15.0),
            backoff_handler=HttpBackoffHandler(max_retries=0),
            allow_private_ips=allow_private_ips,
            response_policy=PassThroughPolicy(),
        )
        self._lock = asyncio.Lock()
        self._last_error: EndpointSecurityViolationError | InvalidCredentialsError | None = None

    def validate(self) -> EndpointSecurityViolationError | None:
        parsed = httpx.URL(self._token_url)
        if parsed.scheme != "https" and parsed.host not in ("localhost", "127.0.0.1", "testserver"):
            return EndpointSecurityViolationError(
                endpoint=self._token_url,
                message=f"OAuth2 token_url must use HTTPS: {self._token_url}",
            )
        return None

    @property
    def last_error(self) -> EndpointSecurityViolationError | InvalidCredentialsError | None:
        return self._last_error

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
        if self.validate() is not None:
            return False
        if not self._access_token:
            return False
        if self._expires_at_epoch is None:
            return True
        now = datetime.now(UTC).timestamp()
        return now < (self._expires_at_epoch - self._refresh_buffer_seconds)

    async def _execute_token_refresh_request(self) -> dict[str, object] | None:
        try:
            resp = await self._http_client.request(
                "POST",
                self._token_url,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": self._refresh_token or "",
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                },
            )
            if not resp.is_success:
                self._last_error = InvalidCredentialsError(
                    field_name="refresh_token",
                    message=f"OAuth2 token refresh failed with HTTP {resp.status_code}",
                )
                logger.error(
                    "oauth2_token_refresh_http_error",
                    token_url=self._token_url,
                    status_code=resp.status_code,
                )
                return None
            payload = resp.json()
            if not isinstance(payload, dict):
                self._last_error = InvalidCredentialsError(
                    field_name="access_token",
                    message="Token response was not a JSON object",
                )
                return None
            return payload
        except SsrfSecurityError as exc:
            self._last_error = EndpointSecurityViolationError(
                endpoint=self._token_url,
                message=str(exc),
            )
            logger.error(
                "oauth2_token_refresh_ssrf_violation",
                token_url=self._token_url,
                error=str(exc),
            )
            return None
        except (HttpError, httpx.HTTPError, OSError, ValueError) as exc:
            self._last_error = InvalidCredentialsError(
                field_name="refresh_token",
                message=f"OAuth2 token refresh failed: {exc}",
            )
            logger.error(
                "oauth2_token_refresh_network_error",
                token_url=self._token_url,
                error=str(exc),
            )
            return None

    async def refresh_if_needed(self) -> bool:
        """Refreshes the token if expired or nearing expiration using shttp.HttpClient."""
        url_err = self.validate()
        if url_err is not None:
            self._last_error = url_err
            logger.error(
                "oauth2_invalid_token_url",
                token_url=self._token_url,
                error=url_err.message,
            )
            return False

        async with self._lock:
            if await self.is_valid() or not self._refresh_token:
                return False

            payload = await self._execute_token_refresh_request()
            if payload is None:
                return False

            new_access_token = payload.get("access_token")
            if not new_access_token:
                self._last_error = InvalidCredentialsError(
                    field_name="access_token",
                    message="Token response did not include access_token",
                )
                logger.error(
                    "oauth2_token_response_missing_access_token",
                    token_url=self._token_url,
                )
                return False

            self._last_error = None
            new_refresh_token = payload.get("refresh_token") or self._refresh_token
            new_expires_epoch: float | None = None
            expires_in = payload.get("expires_in")
            if isinstance(expires_in, (int, float)):
                new_expires_epoch = datetime.now(UTC).timestamp() + float(expires_in)
            elif isinstance(expires_in, str):
                try:
                    new_expires_epoch = datetime.now(UTC).timestamp() + float(expires_in)
                except ValueError:
                    self._last_error = InvalidCredentialsError(
                        field_name="expires_in",
                        message=f"Malformed expires_in in token response: {expires_in}",
                    )
                    logger.error(
                        "oauth2_token_response_invalid_expires_in",
                        token_url=self._token_url,
                        expires_in=expires_in,
                    )
                    return False

            self._access_token = str(new_access_token)
            self._refresh_token = str(new_refresh_token) if new_refresh_token else None
            self._expires_at_epoch = new_expires_epoch

            if self._on_token_refreshed:
                callback_res = self._on_token_refreshed(
                    self._access_token, self._refresh_token, self._expires_at_epoch
                )
                if inspect.isawaitable(callback_res):
                    await callback_res

            return True
