"""Unit tests for PublicInternetEgressPolicy verifying SSRF delegation to platform shttp."""

from __future__ import annotations

from ip.engine.adapters.outbound.connectors.egress_policy import PublicInternetEgressPolicy
from ip.engine.domain.exceptions import EndpointSecurityViolationError


def test_public_internet_egress_policy_allows_valid_https() -> None:
    policy = PublicInternetEgressPolicy()
    result = policy.validate_url("https://api.github.com/events")
    assert result.is_ok is True
    assert result.value is None


def test_public_internet_egress_policy_blocks_private_ip_by_default() -> None:
    policy = PublicInternetEgressPolicy(allow_private_ips=False)
    result = policy.validate_url("http://127.0.0.1:8080/metrics")
    assert result.is_err is True
    assert isinstance(result.error, EndpointSecurityViolationError)
    assert result.error.endpoint == "http://127.0.0.1:8080/metrics"


def test_public_internet_egress_policy_allows_private_ip_when_configured() -> None:
    policy = PublicInternetEgressPolicy(allow_private_ips=True)
    result = policy.validate_url("http://127.0.0.1:8080/metrics")
    assert result.is_ok is True
    assert result.value is None


def test_public_internet_egress_policy_rejects_unsupported_scheme() -> None:
    policy = PublicInternetEgressPolicy()
    result = policy.validate_url("ftp://ftp.example.com/files")
    assert result.is_err is True
    assert isinstance(result.error, EndpointSecurityViolationError)


def test_public_internet_egress_policy_rejects_missing_hostname() -> None:
    policy = PublicInternetEgressPolicy()
    result = policy.validate_url("https:///no-host")
    assert result.is_err is True
    assert isinstance(result.error, EndpointSecurityViolationError)


def test_public_internet_egress_policy_rejects_insecure_http_for_public_host() -> None:
    policy = PublicInternetEgressPolicy(allow_private_ips=False)
    result = policy.validate_url("http://api.example.com/events")
    assert result.is_err is True
    assert isinstance(result.error, EndpointSecurityViolationError)
    assert "Insecure scheme 'http'" in result.error.message
