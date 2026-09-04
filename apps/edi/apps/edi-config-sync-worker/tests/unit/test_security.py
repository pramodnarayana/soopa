import socket

import pytest
from edi.adapters.outbound.security.network import (
    get_safe_ip,
    ssrf_safe_context,
    validate_target_url,
)


@pytest.fixture(autouse=True)
def disable_dev_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable IS_DEV for all security tests to ensure SSRF validation is active."""
    # Instead of mocking settings, we set the environment variable
    monkeypatch.setenv("ENV", "production")


def test_validate_target_url_invalid_scheme() -> None:
    assert not validate_target_url("ftp://example.com")
    assert not validate_target_url("file:///etc/passwd")


def test_validate_target_url_no_hostname() -> None:
    assert not validate_target_url("http://")


def test_validate_target_url_valid() -> None:
    # example.com naturally resolves to a public IP
    assert validate_target_url("http://example.com")


def test_validate_target_url_private_ip() -> None:
    # Passing a raw private IP avoids needing DNS
    assert not validate_target_url("http://192.168.1.1")


def test_validate_target_url_loopback_ip() -> None:
    assert not validate_target_url("http://localhost")


def test_get_safe_ip() -> None:
    # Resolves to a real IP
    ip = get_safe_ip("example.com")
    assert ip is not None
    assert not ip.startswith("192.168.")
    assert not ip.startswith("127.")


def test_get_safe_ip_private() -> None:
    assert get_safe_ip("192.168.1.1") is None


def test_ssrf_safe_context_valid() -> None:
    with ssrf_safe_context("http://example.com"):
        res = socket.getaddrinfo("example.com", 80)
        assert res
        assert len(res) > 0
        # Under the context, it should resolve to the bound IP, not perform a fresh DNS lookup
        ip_addr = res[0][4][0]
        assert not ip_addr.startswith("192.168.")
        assert not ip_addr.startswith("127.")


def test_ssrf_safe_context_invalid_url() -> None:
    with pytest.raises(ValueError), ssrf_safe_context("ftp://example.com"):
        pass
