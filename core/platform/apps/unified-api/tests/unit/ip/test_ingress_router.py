"""Pure zero-mock unit tests for ingress router header filtering."""

from __future__ import annotations

from ip.engine.adapters.inbound.api.routers.ingress_router import (
    _is_allowed_ingress_header,
)


def test_is_allowed_ingress_header_blocks_sensitive_headers() -> None:
    # Must block sensitive credentials case-insensitively
    assert _is_allowed_ingress_header("Authorization") is False
    assert _is_allowed_ingress_header("authorization") is False
    assert _is_allowed_ingress_header("Cookie") is False
    assert _is_allowed_ingress_header("Set-Cookie") is False
    assert _is_allowed_ingress_header("X-API-KEY") is False
    assert _is_allowed_ingress_header("x-api-key") is False
    assert _is_allowed_ingress_header("Proxy-Authorization") is False
    assert _is_allowed_ingress_header("X-Auth-Token") is False
    assert _is_allowed_ingress_header("X-Client-Secret") is False
    assert _is_allowed_ingress_header("X-Custom-Password") is False
    assert _is_allowed_ingress_header("X-User-Session") is False
    assert _is_allowed_ingress_header("X-Bearer-Token") is False


def test_is_allowed_ingress_header_allows_metadata_and_webhook_signatures() -> None:
    assert _is_allowed_ingress_header("Content-Type") is True
    assert _is_allowed_ingress_header("User-Agent") is True
    assert _is_allowed_ingress_header("X-Correlation-ID") is True
    assert _is_allowed_ingress_header("X-Request-ID") is True
    assert _is_allowed_ingress_header("X-Vendor") is True
    assert _is_allowed_ingress_header("X-Idempotency-Key") is True
    assert _is_allowed_ingress_header("idempotency-key") is True
    assert _is_allowed_ingress_header("stripe-signature") is True
    assert _is_allowed_ingress_header("x-hub-signature-256") is True
