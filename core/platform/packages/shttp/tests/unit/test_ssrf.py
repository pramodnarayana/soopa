"""Unit tests for SSRF protection and DNS pinning."""

from __future__ import annotations

import ipaddress
import socket

import pytest
from shttp.exceptions import SsrfSecurityError, SsrfViolationReason
from shttp.security.ssrf import (
    get_safe_ip,
    is_ip_private_or_restricted,
    ssrf_safe_context,
    validate_target_url,
)


def test_validate_target_url_schemes() -> None:
    assert validate_target_url("ftp://example.com") is False
    assert validate_target_url("file:///etc/passwd") is False
    assert validate_target_url("gopher://example.com") is False
    assert validate_target_url("http://") is False


def test_validate_target_url_unresolvable_hostname() -> None:
    assert validate_target_url("http://this-hostname-definitely-does-not-exist-12345.org") is False


def test_is_ip_private_or_restricted() -> None:
    assert is_ip_private_or_restricted(ipaddress.ip_address("127.0.0.1")) is True
    assert is_ip_private_or_restricted(ipaddress.ip_address("10.0.0.1")) is True
    assert is_ip_private_or_restricted(ipaddress.ip_address("192.168.1.1")) is True
    assert is_ip_private_or_restricted(ipaddress.ip_address("169.254.169.254")) is True
    assert is_ip_private_or_restricted(ipaddress.ip_address("224.0.0.1")) is True
    assert is_ip_private_or_restricted(ipaddress.ip_address("8.8.8.8")) is False
    assert is_ip_private_or_restricted(ipaddress.ip_address("1.1.1.1")) is False


def test_get_safe_ip() -> None:
    # Test private IPs natively without mocking
    assert get_safe_ip("10.0.0.1", allow_private_ips=False) is None
    assert get_safe_ip("10.0.0.1", allow_private_ips=True) == "10.0.0.1"
    assert get_safe_ip("127.0.0.1", allow_private_ips=False) is None
    assert get_safe_ip("127.0.0.1", allow_private_ips=True) == "127.0.0.1"

    # AWS IMDS and link-local must NEVER be allowed even if allow_private_ips=True
    assert get_safe_ip("169.254.169.254", allow_private_ips=True) is None
    assert get_safe_ip("fe80::1", allow_private_ips=True) is None
    assert validate_target_url("http://169.254.169.254", allow_private_ips=True) is False

    # Test public IPs natively without mocking
    assert get_safe_ip("8.8.8.8") == "8.8.8.8"
    assert get_safe_ip("1.1.1.1") == "1.1.1.1"


def test_ssrf_safe_context_pinning() -> None:
    # Pin safe public IP natively
    with ssrf_safe_context("https://8.8.8.8/api"):
        res = socket.getaddrinfo("8.8.8.8", 443)
        assert res[0][4][0] == "8.8.8.8"

    # Block restricted private IP natively
    with (
        pytest.raises(SsrfSecurityError) as exc_info,
        ssrf_safe_context("http://127.0.0.1/api", allow_private_ips=False),
    ):
        pass
    assert exc_info.value.reason == SsrfViolationReason.RESTRICTED_IP
    assert exc_info.value.classify().value == "SECURITY_VIOLATION"

    # Invalid URL scheme raises SsrfSecurityError
    with pytest.raises(SsrfSecurityError) as exc_info, ssrf_safe_context("ftp://8.8.8.8"):
        pass
    assert exc_info.value.reason == SsrfViolationReason.INVALID_SCHEME
    assert exc_info.value.classify().value == "SECURITY_VIOLATION"

    # Missing hostname raises SsrfSecurityError
    with pytest.raises(SsrfSecurityError) as exc_info, ssrf_safe_context("http://"):
        pass
    assert exc_info.value.reason == SsrfViolationReason.MISSING_HOSTNAME


def test_ssrf_safe_context_unresolvable_hostname() -> None:
    # RFC 2606 reserves .invalid so DNS resolution is guaranteed to fail natively
    with (
        pytest.raises(SsrfSecurityError) as exc_info,
        ssrf_safe_context("http://unresolvable-test.invalid"),
    ):
        pass
    assert exc_info.value.reason == SsrfViolationReason.UNRESOLVABLE_HOST
