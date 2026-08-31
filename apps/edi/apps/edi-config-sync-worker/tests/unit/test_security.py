from unittest.mock import MagicMock, patch

import pytest
from edi.adapters.outbound.security.network import (
    get_safe_ip,
    ssrf_safe_context,
    validate_target_url,
)


@pytest.fixture(autouse=True)
def disable_dev_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable IS_DEV for all security tests to ensure SSRF validation is active."""
    import edi.adapters.outbound.security.network
    from edi.config.settings import AppSettings

    mock_settings = MagicMock(spec=AppSettings)
    mock_settings.env = "production"
    monkeypatch.setattr(
        edi.adapters.outbound.security.network, "get_settings", lambda: mock_settings
    )


def test_validate_target_url_invalid_scheme() -> None:
    assert not validate_target_url("ftp://example.com")
    assert not validate_target_url("file:///etc/passwd")


def test_validate_target_url_no_hostname() -> None:
    assert not validate_target_url("http://")


@patch("socket.getaddrinfo")
def test_validate_target_url_valid(mock_getaddrinfo: MagicMock) -> None:
    mock_getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 80))]
    assert validate_target_url("http://example.com")


@patch("socket.getaddrinfo")
def test_validate_target_url_private_ip(mock_getaddrinfo: MagicMock) -> None:
    mock_getaddrinfo.return_value = [(2, 1, 6, "", ("192.168.1.1", 80))]
    assert not validate_target_url("http://internal.com")


@patch("socket.getaddrinfo")
def test_validate_target_url_loopback_ip(mock_getaddrinfo: MagicMock) -> None:
    mock_getaddrinfo.return_value = [(2, 1, 6, "", ("127.0.0.1", 80))]
    assert not validate_target_url("http://localhost")


@patch("socket.getaddrinfo")
def test_get_safe_ip(mock_getaddrinfo: MagicMock) -> None:
    mock_getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 80))]
    assert get_safe_ip("example.com") == "93.184.216.34"


@patch("socket.getaddrinfo")
def test_get_safe_ip_private(mock_getaddrinfo: MagicMock) -> None:
    mock_getaddrinfo.return_value = [(2, 1, 6, "", ("192.168.1.1", 80))]
    assert get_safe_ip("example.com") is None


@patch("edi.adapters.outbound.security.network._orig_getaddrinfo")
def test_ssrf_safe_context_valid(mock_getaddrinfo: MagicMock) -> None:
    mock_getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 80))]
    with ssrf_safe_context("http://example.com"):
        import socket

        res = socket.getaddrinfo("example.com", 80)
        assert res == [(2, 1, 6, "", ("93.184.216.34", 80))]
        mock_getaddrinfo.assert_called_with("93.184.216.34", 80, 0, 0, 0, 0)


def test_ssrf_safe_context_invalid_url() -> None:
    with pytest.raises(ValueError), ssrf_safe_context("ftp://example.com"):
        pass
