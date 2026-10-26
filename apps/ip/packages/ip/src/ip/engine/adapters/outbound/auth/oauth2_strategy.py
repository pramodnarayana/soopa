import asyncio
import inspect
import json
import math
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
import structlog
from ip.engine.domain.enums import FailureDisposition
from ip.engine.domain.exceptions import (
    EndpointSecurityViolationError,
    InvalidCredentialsError,
    IpError,
    Result,
    UpstreamHttpError,
    UpstreamNetworkError,
)
from ip.engine.ports.outbound.auth_strategy_port import AuthenticatorPort
from ip.engine.ports.outbound.token_refresh_lock_port import (
    OAuth2TokenRefresherPort,
    RefreshedOAuth2TokensDTO,
)
from seedwork.domain.types import JsonDict
from shttp import HttpClient, HttpError, PassThroughPolicy, create_http_client
from shttp.exceptions import SsrfSecurityError
from shttp.resilience import HttpBackoffHandler

logger = structlog.get_logger(__name__)

TokenRefreshCallback = Callable[[str, str | None, float | None], Awaitable[None] | None]


@dataclass(frozen=True)
class OAuth2TokenResponseDTO:
    """Strongly-typed parsed OAuth2 token endpoint response."""

    access_token: str
    refresh_token: str | None = None
    expires_at_epoch: float | None = None


class OAuth2Strategy(AuthenticatorPort):
    """Handles OAuth 2.0 bearer authorization and token renewal via centralized shttp.HttpClient."""

    @property
    def sensitive_header_names(self) -> Sequence[str]:
        return ("Authorization",)

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
        grant_mode: str = "refresh_token",
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
        self._grant_mode = grant_mode
        self._http_client = http_client or HttpClient(
            client=create_http_client(timeout=15.0),
            backoff_handler=HttpBackoffHandler(max_retries=0),
            allow_private_ips=allow_private_ips,
            response_policy=PassThroughPolicy(),
        )
        self._lock = asyncio.Lock()
        self._last_error: IpError | None = None

    def validate(self) -> EndpointSecurityViolationError | None:
        parsed = httpx.URL(self._token_url)
        if parsed.scheme != "https" and parsed.host not in ("localhost", "127.0.0.1", "testserver"):
            return EndpointSecurityViolationError(
                endpoint=self._token_url,
                message=f"OAuth2 token_url must use HTTPS: {self._token_url}",
            )
        return None

    @property
    def last_error(self) -> IpError | None:
        return self._last_error

    @property
    def access_token(self) -> str:
        return self._access_token

    @property
    def refresh_token(self) -> str | None:
        return self._refresh_token

    @property
    def expires_at_epoch(self) -> float | None:
        return self._expires_at_epoch

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

    def _build_token_request_payload(self) -> dict[str, str]:
        form_payload: dict[str, str] = {
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }
        if self._grant_mode == "client_credentials" or (
            not self._refresh_token and self._client_id
        ):
            form_payload["grant_type"] = "client_credentials"
        else:
            form_payload["grant_type"] = "refresh_token"
            form_payload["refresh_token"] = self._refresh_token or ""
        return form_payload

    def _classify_token_error_response(self, resp: httpx.Response) -> IpError:
        if resp.status_code == 429 or resp.status_code >= 500:
            return UpstreamHttpError(
                status_code=resp.status_code,
                message=f"OAuth2 token endpoint transient HTTP {resp.status_code}",
                disposition=FailureDisposition.RETRY,
            )

        error_code: str = ""
        error_description: str = ""
        try:
            error_body = resp.json()
            if isinstance(error_body, dict):
                error_code = str(error_body.get("error") or "").strip().lower()
                error_description = str(error_body.get("error_description") or "").strip()
        except (ValueError, json.JSONDecodeError):
            logger.debug(
                "oauth2_token_error_response_not_json",
                status_code=resp.status_code,
                token_url=self._token_url,
            )

        if error_code == "invalid_grant":
            return InvalidCredentialsError(
                field_name="refresh_token",
                message=f"OAuth2 refresh token revoked or expired: {error_description or 'invalid_grant'}",
            )

        detail = error_description or error_code or f"HTTP {resp.status_code}"
        return UpstreamHttpError(
            status_code=resp.status_code,
            message=f"OAuth2 token refresh failed: {detail}",
            disposition=FailureDisposition.FAIL,
        )

    def _parse_token_success_response(
        self, resp: httpx.Response
    ) -> Result[OAuth2TokenResponseDTO, IpError]:
        try:
            payload = resp.json()
        except (ValueError, json.JSONDecodeError):
            return Result.fail(
                UpstreamHttpError(
                    status_code=resp.status_code,
                    message="Token response was not valid JSON",
                    disposition=FailureDisposition.FAIL,
                )
            )
        if not isinstance(payload, dict):
            return Result.fail(
                UpstreamHttpError(
                    status_code=resp.status_code,
                    message="Token response was not a JSON object",
                    disposition=FailureDisposition.FAIL,
                )
            )

        new_access_token = payload.get("access_token")
        if not new_access_token:
            logger.error(
                "oauth2_token_response_missing_access_token",
                token_url=self._token_url,
            )
            return Result.fail(
                InvalidCredentialsError(
                    field_name="access_token",
                    message="Token response did not include access_token",
                )
            )

        new_expires_epoch, expires_err = self._parse_expires_in(payload.get("expires_in"))
        if expires_err is not None:
            logger.error(
                "oauth2_token_response_invalid_expires_in",
                token_url=self._token_url,
                expires_in=str(payload.get("expires_in")),
            )
            return Result.fail(expires_err)

        raw_rt = payload.get("refresh_token") or self._refresh_token
        return Result.ok(
            OAuth2TokenResponseDTO(
                access_token=str(new_access_token),
                refresh_token=str(raw_rt) if raw_rt else None,
                expires_at_epoch=new_expires_epoch,
            )
        )

    async def _execute_token_refresh_request(
        self,
    ) -> Result[OAuth2TokenResponseDTO, IpError]:
        try:
            form_payload = self._build_token_request_payload()
            resp = await self._http_client.request(
                "POST",
                self._token_url,
                data=form_payload,
            )
            if not resp.is_success:
                err = self._classify_token_error_response(resp)
                logger.error(
                    "oauth2_token_refresh_http_error",
                    token_url=self._token_url,
                    status_code=resp.status_code,
                )
                return Result.fail(err)

            return self._parse_token_success_response(resp)
        except SsrfSecurityError as exc:
            logger.error(
                "oauth2_token_refresh_ssrf_violation",
                token_url=self._token_url,
                error=str(exc),
            )
            return Result.fail(
                EndpointSecurityViolationError(
                    endpoint=self._token_url,
                    message=str(exc),
                )
            )
        except (HttpError, httpx.HTTPError, OSError) as exc:
            logger.error(
                "oauth2_token_refresh_network_error",
                token_url=self._token_url,
                error=str(exc),
            )
            return Result.fail(
                UpstreamNetworkError(
                    endpoint=self._token_url,
                    message=f"OAuth2 token refresh network failure: {exc}",
                )
            )
        except ValueError as exc:
            logger.error(
                "oauth2_token_refresh_decode_error",
                token_url=self._token_url,
                error=str(exc),
            )
            return Result.fail(
                InvalidCredentialsError(
                    field_name="refresh_token",
                    message=f"OAuth2 token refresh malformed response: {exc}",
                )
            )

    def _parse_expires_in(
        self, expires_in: object
    ) -> tuple[float | None, InvalidCredentialsError | None]:
        if expires_in is None:
            return None, None
        parsed: float
        if isinstance(expires_in, (int, float)):
            parsed = float(expires_in)
        elif isinstance(expires_in, str):
            try:
                parsed = float(expires_in)
            except ValueError:
                return None, InvalidCredentialsError(
                    field_name="expires_in",
                    message=f"Malformed expires_in in token response: {expires_in}",
                )
        else:
            return None, InvalidCredentialsError(
                field_name="expires_in",
                message=f"Unsupported expires_in type in token response: {type(expires_in).__name__}",
            )

        if math.isnan(parsed) or math.isinf(parsed) or parsed <= 0:
            return None, InvalidCredentialsError(
                field_name="expires_in",
                message=f"Non-positive or non-finite expires_in in token response: {expires_in}",
            )
        return datetime.now(UTC).timestamp() + parsed, None

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
            if await self.is_valid():
                return False

            can_use_client_credentials = self._grant_mode == "client_credentials" or (
                not self._refresh_token and bool(self._client_id)
            )
            if not self._refresh_token and not can_use_client_credentials:
                return False

            refresh_res = await self._execute_token_refresh_request()
            if refresh_res.is_err or refresh_res.value is None:
                self._last_error = refresh_res.error
                return False

            token_dto = refresh_res.value
            self._last_error = None
            self._access_token = token_dto.access_token
            self._refresh_token = token_dto.refresh_token
            self._expires_at_epoch = token_dto.expires_at_epoch

            if self._on_token_refreshed:
                callback_res = self._on_token_refreshed(
                    self._access_token, self._refresh_token, self._expires_at_epoch
                )
                if inspect.isawaitable(callback_res):
                    await callback_res

            return True


class OAuth2StrategyTokenRefresher(OAuth2TokenRefresherPort):
    """Adapter implementing OAuth2TokenRefresherPort via OAuth2Strategy."""

    def __init__(
        self,
        *,
        http_client: HttpClient | None = None,
        allow_private_ips: bool = False,
    ) -> None:
        self._http_client = http_client or HttpClient(
            client=create_http_client(timeout=15.0),
            backoff_handler=HttpBackoffHandler(max_retries=0),
            allow_private_ips=allow_private_ips,
            response_policy=PassThroughPolicy(),
        )
        self._allow_private_ips = allow_private_ips

    async def refresh_tokens(
        self,
        *,
        public_config: JsonDict,
        credentials: JsonDict,
        grant_mode: str = "refresh_token",
    ) -> Result[RefreshedOAuth2TokensDTO, IpError]:
        token_url = str(
            credentials.get("token_url") or public_config.get("token_url") or ""
        ).strip()
        client_id = str(
            credentials.get("client_id") or public_config.get("client_id") or ""
        ).strip()
        client_secret = str(credentials.get("client_secret") or "").strip()
        refresh_token_raw = credentials.get("refresh_token")
        refresh_token = str(refresh_token_raw).strip() if refresh_token_raw else None

        if not token_url:
            return Result.fail(
                InvalidCredentialsError(
                    field_name="token_url",
                    message="OAuth2 refresh requires 'token_url' in credentials or public_config.",
                )
            )

        strategy = OAuth2Strategy(
            client_id=client_id,
            client_secret=client_secret,
            token_url=token_url,
            access_token=str(credentials.get("access_token") or ""),
            refresh_token=refresh_token,
            expires_at_epoch=0.0,  # Force expiration so refresh_if_needed() executes exchange
            http_client=self._http_client,
            allow_private_ips=self._allow_private_ips,
            grant_mode=grant_mode,
        )
        refreshed = await strategy.refresh_if_needed()
        if not refreshed:
            err: IpError = strategy.last_error or InvalidCredentialsError(
                field_name="refresh_token",
                message="OAuth2 token refresh did not succeed.",
            )
            return Result.fail(err)

        return Result.ok(
            RefreshedOAuth2TokensDTO(
                access_token=strategy.access_token,
                refresh_token=strategy.refresh_token,
                expires_at_epoch=strategy.expires_at_epoch,
            )
        )
