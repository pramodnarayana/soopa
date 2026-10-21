"""Unit tests for outbound network security adapter."""

from __future__ import annotations

import socket

import pytest
from edi.adapters.outbound.security.network import (
    get_safe_ip,
    ssrf_safe_context,
    validate_target_url,
)

PUBLIC_IP = "93.184.216.34"


@pytest.fixture(autouse=True)
def disable_dev_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable IS_DEV for all security tests to ensure SSRF validation is active."""
    monkeypatch.setenv("ENV", "production")


def test_validate_target_url_invalid_scheme() -> None:
    assert not validate_target_url("ftp://example.com")
    assert not validate_target_url("file:///etc/passwd")


def test_validate_target_url_no_hostname() -> None:
    assert not validate_target_url("http://")


def test_validate_target_url_valid() -> None:
    assert validate_target_url(f"http://{PUBLIC_IP}")


def test_validate_target_url_private_ip() -> None:
    assert not validate_target_url("http://192.168.1.1")


def test_validate_target_url_loopback_ip() -> None:
    assert not validate_target_url("http://127.0.0.1")


def test_validate_target_url_unresolvable_hostname() -> None:
    assert not validate_target_url("http://unresolvable.invalid")


def test_get_safe_ip() -> None:
    assert get_safe_ip(PUBLIC_IP) == PUBLIC_IP


def test_get_safe_ip_private() -> None:
    assert get_safe_ip("192.168.1.1") is None


def test_ssrf_safe_context_valid() -> None:
    with ssrf_safe_context(f"http://{PUBLIC_IP}"):
        result = socket.getaddrinfo(PUBLIC_IP, 80)
        assert result[0][4][0] == PUBLIC_IP


def test_ssrf_safe_context_invalid_url() -> None:
    with pytest.raises(ValueError), ssrf_safe_context("ftp://example.com"):
        pass
