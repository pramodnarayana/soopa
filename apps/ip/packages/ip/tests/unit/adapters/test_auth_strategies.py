"""Unit tests for authentication strategies."""

import base64
from datetime import UTC, datetime

import httpx
import pytest
from ip.adapters.outbound.auth.api_key_auth_strategy import (
    ApiKeyAuthStrategy,
    ApiKeyPlacement,
)
from ip.adapters.outbound.auth.basic_auth_strategy import BasicAuthStrategy
from ip.adapters.outbound.auth.bearer_auth_strategy import BearerAuthStrategy
from ip.adapters.outbound.auth.no_auth_strategy import NoAuthStrategy
from ip.adapters.outbound.auth.oauth2_strategy import OAuth2Strategy


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
