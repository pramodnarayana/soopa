"""Zero-mock tests for authentication strategies using local HTTP socket server (pytest_httpserver)."""

import base64
from datetime import UTC, datetime

import httpx
import pytest
from ip.engine.adapters.outbound.auth.api_key_auth_strategy import (
    ApiKeyAuthStrategy,
    ApiKeyPlacement,
)
from ip.engine.adapters.outbound.auth.basic_auth_strategy import BasicAuthStrategy
from ip.engine.adapters.outbound.auth.bearer_auth_strategy import BearerAuthStrategy
from ip.engine.adapters.outbound.auth.no_auth_strategy import NoAuthStrategy
from ip.engine.adapters.outbound.auth.oauth2_strategy import (
    OAuth2Strategy,
    OAuth2StrategyTokenRefresher,
)
from ip.engine.domain.enums import FailureDisposition
from ip.engine.domain.exceptions import (
    EndpointSecurityViolationError,
    InvalidCredentialsError,
    UpstreamHttpError,
)
from pytest_httpserver import HTTPServer


def test_no_auth_strategy_leaves_request_untouched() -> None:
    strategy = NoAuthStrategy()
    req = httpx.Request("GET", "https://api.example.com/test")

    out_req = strategy.authenticate_request(req)
    assert "Authorization" not in out_req.headers


def test_basic_auth_strategy_injects_header() -> None:
    strategy = BasicAuthStrategy(username="admin", password="secret_password")
    req = httpx.Request("GET", "https://api.example.com/test")

    out_req = strategy.authenticate_request(req)
    expected_token = base64.b64encode(b"admin:secret_password").decode("ascii")
    assert out_req.headers["Authorization"] == f"Basic {expected_token}"


def test_bearer_auth_strategy_injects_header() -> None:
    strategy = BearerAuthStrategy(token="tok_123456789")
    req = httpx.Request("GET", "https://api.example.com/test")

    out_req = strategy.authenticate_request(req)
    assert out_req.headers["Authorization"] == "Bearer tok_123456789"


def test_api_key_auth_strategy_header() -> None:
    strategy = ApiKeyAuthStrategy(
        api_key="key_xyz", param_name="X-Custom-Token", placement=ApiKeyPlacement.HEADER
    )
    req = httpx.Request("GET", "https://api.example.com/test")

    out_req = strategy.authenticate_request(req)
    assert out_req.headers["X-Custom-Token"] == "key_xyz"


def test_api_key_auth_strategy_query_param() -> None:
    strategy = ApiKeyAuthStrategy(
        api_key="key_xyz", param_name="api_key", placement=ApiKeyPlacement.QUERY_PARAM
    )
    req = httpx.Request("GET", "https://api.example.com/test?limit=10")

    out_req = strategy.authenticate_request(req)
    assert out_req.url.params["api_key"] == "key_xyz"
    assert out_req.url.params["limit"] == "10"


@pytest.mark.asyncio
async def test_oauth2_strategy_is_valid() -> None:
    # Token valid for 1 hour
    future_epoch = datetime.now(UTC).timestamp() + 3600
    strategy = OAuth2Strategy(
        client_id="cid",
        client_secret="sec",
        token_url="https://auth.example.com/token",
        access_token="tok_active",
        refresh_token="ref_active",
        expires_at_epoch=future_epoch,
    )

    assert await strategy.is_valid() is True

    req = httpx.Request("GET", "https://api.example.com/test")
    out_req = strategy.authenticate_request(req)
    assert out_req.headers["Authorization"] == "Bearer tok_active"


@pytest.mark.asyncio
async def test_oauth2_strategy_detects_expiration() -> None:
    # Token expired 10 minutes ago
    past_epoch = datetime.now(UTC).timestamp() - 600
    strategy = OAuth2Strategy(
        client_id="cid",
        client_secret="sec",
        token_url="https://auth.example.com/token",
        access_token="tok_expired",
        refresh_token="ref_token",
        expires_at_epoch=past_epoch,
    )

    assert await strategy.is_valid() is False


@pytest.mark.asyncio
async def test_oauth2_strategy_refresh_via_shttp_and_async_callback(
    httpserver: HTTPServer,
) -> None:
    past_epoch = datetime.now(UTC).timestamp() - 600
    refreshed_values: list[tuple[str, str | None, float | None]] = []

    async def on_refreshed(access_tok: str, refresh_tok: str | None, exp: float | None) -> None:
        refreshed_values.append((access_tok, refresh_tok, exp))

    httpserver.expect_request(
        "/oauth/token",
        method="POST",
    ).respond_with_json(
        {
            "access_token": "tok_fresh_999",
            "refresh_token": "ref_fresh_999",
            "expires_in": 3600,
        },
        status=200,
    )

    strategy = OAuth2Strategy(
        client_id="cid",
        client_secret="sec",
        token_url=httpserver.url_for("/oauth/token"),
        access_token="tok_expired",
        refresh_token="ref_old",
        expires_at_epoch=past_epoch,
        on_token_refreshed=on_refreshed,
        allow_private_ips=True,
    )

    did_refresh = await strategy.refresh_if_needed()
    assert did_refresh is True
    assert strategy.access_token == "tok_fresh_999"
    assert strategy.refresh_token == "ref_fresh_999"
    assert strategy.last_error is None
    assert len(refreshed_values) == 1
    assert refreshed_values[0][0] == "tok_fresh_999"

    # Rejects insecure non-localhost HTTP token_url without raising
    insecure_strategy = OAuth2Strategy(
        client_id="cid",
        client_secret="sec",
        token_url="http://insecure.example.com/oauth/token",
        access_token="tok_expired",
        refresh_token="ref_old",
        expires_at_epoch=past_epoch,
    )
    assert await insecure_strategy.refresh_if_needed() is False
    assert isinstance(insecure_strategy.last_error, EndpointSecurityViolationError)

    # Handles 401 token refresh failure gracefully via PassThroughPolicy
    httpserver.expect_request(
        "/oauth/token_fail",
        method="POST",
    ).respond_with_json({"error": "invalid_grant"}, status=401)

    fail_strategy = OAuth2Strategy(
        client_id="cid",
        client_secret="sec",
        token_url=httpserver.url_for("/oauth/token_fail"),
        access_token="tok_expired",
        refresh_token="ref_old",
        expires_at_epoch=past_epoch,
        allow_private_ips=True,
    )
    assert await fail_strategy.refresh_if_needed() is False
    assert isinstance(fail_strategy.last_error, InvalidCredentialsError)

    # Supports client_credentials grant refresh without a refresh_token
    httpserver.expect_request(
        "/oauth/token_client_credentials",
        method="POST",
    ).respond_with_json(
        {
            "access_token": "tok_cc_123",
            "expires_in": 1800,
        },
        status=200,
    )
    cc_strategy = OAuth2Strategy(
        client_id="cid",
        client_secret="sec",
        token_url=httpserver.url_for("/oauth/token_client_credentials"),
        access_token="tok_expired",
        refresh_token=None,
        grant_mode="client_credentials",
        expires_at_epoch=past_epoch,
        allow_private_ips=True,
    )
    assert await cc_strategy.refresh_if_needed() is True
    assert cc_strategy.access_token == "tok_cc_123"


@pytest.mark.asyncio
async def test_oauth2_strategy_token_refresher_distinguishes_503_transient_vs_400_terminal(
    httpserver: HTTPServer,
) -> None:
    refresher = OAuth2StrategyTokenRefresher(allow_private_ips=True)

    # 1. 503 Service Unavailable from IdP -> UpstreamHttpError (FailureDisposition.RETRY)
    httpserver.expect_request(
        "/oauth/token_503",
        method="POST",
    ).respond_with_json({"error": "temporarily_unavailable"}, status=503)

    res_503 = await refresher.refresh_tokens(
        public_config={"token_url": httpserver.url_for("/oauth/token_503")},
        credentials={
            "client_id": "cid",
            "client_secret": "sec",
            "refresh_token": "ref_1",
        },
    )
    assert res_503.is_err is True
    assert isinstance(res_503.error, UpstreamHttpError)
    assert res_503.error.disposition == FailureDisposition.RETRY

    # 2. 400 invalid_grant from IdP -> InvalidCredentialsError (FailureDisposition.FAIL)
    httpserver.expect_request(
        "/oauth/token_400",
        method="POST",
    ).respond_with_json({"error": "invalid_grant"}, status=400)

    res_400 = await refresher.refresh_tokens(
        public_config={"token_url": httpserver.url_for("/oauth/token_400")},
        credentials={
            "client_id": "cid",
            "client_secret": "sec",
            "refresh_token": "ref_revoked",
        },
    )
    assert res_400.is_err is True
    assert isinstance(res_400.error, InvalidCredentialsError)
    assert res_400.error.disposition == FailureDisposition.FAIL

    # 3. 200 OK from IdP -> RefreshedOAuth2TokensDTO with rotated refresh_token
    httpserver.expect_request(
        "/oauth/token_200",
        method="POST",
    ).respond_with_json(
        {
            "access_token": "tok_rotated_200",
            "refresh_token": "ref_rotated_200",
            "expires_in": 3600,
        },
        status=200,
    )

    res_200 = await refresher.refresh_tokens(
        public_config={"token_url": httpserver.url_for("/oauth/token_200")},
        credentials={
            "client_id": "cid",
            "client_secret": "sec",
            "refresh_token": "ref_valid",
        },
    )
    assert res_200.is_ok is True
    token_set = res_200.unwrap()
    assert token_set.access_token == "tok_rotated_200"
    assert token_set.refresh_token == "ref_rotated_200"
    assert token_set.expires_at_epoch is not None
