from unittest.mock import patch

import pytest

from worker.core.security import get_safe_ip, ssrf_safe_context, validate_target_url


@pytest.fixture(autouse=True)
def disable_dev_mode(monkeypatch):
    """Disable IS_DEV for all security tests to ensure SSRF validation is active."""
    import worker.core.security

    monkeypatch.setattr(worker.core.security, "IS_DEV", False)


def test_validate_target_url_invalid_scheme():
    assert not validate_target_url("ftp://example.com")
    assert not validate_target_url("file:///etc/passwd")


def test_validate_target_url_no_hostname():
    assert not validate_target_url("http://")


@patch("socket.getaddrinfo")
def test_validate_target_url_valid(mock_getaddrinfo):
    mock_getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 80))]
    assert validate_target_url("http://example.com")


@patch("socket.getaddrinfo")
def test_validate_target_url_private_ip(mock_getaddrinfo):
    mock_getaddrinfo.return_value = [(2, 1, 6, "", ("192.168.1.1", 80))]
    assert not validate_target_url("http://internal.com")


@patch("socket.getaddrinfo")
def test_validate_target_url_loopback_ip(mock_getaddrinfo):
    mock_getaddrinfo.return_value = [(2, 1, 6, "", ("127.0.0.1", 80))]
    assert not validate_target_url("http://localhost")


@patch("socket.getaddrinfo")
def test_get_safe_ip(mock_getaddrinfo):
    mock_getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 80))]
    assert get_safe_ip("example.com") == "93.184.216.34"


@patch("socket.getaddrinfo")
def test_get_safe_ip_private(mock_getaddrinfo):
    mock_getaddrinfo.return_value = [(2, 1, 6, "", ("192.168.1.1", 80))]
    assert get_safe_ip("example.com") is None


@patch("worker.core.security._orig_getaddrinfo")
def test_ssrf_safe_context_valid(mock_getaddrinfo):
    mock_getaddrinfo.return_value = [(2, 1, 6, "", ("93.184.216.34", 80))]
    with ssrf_safe_context("http://example.com"):
        import socket

        res = socket.getaddrinfo("example.com", 80)
        assert res == [(2, 1, 6, "", ("93.184.216.34", 80))]
        mock_getaddrinfo.assert_called_with("93.184.216.34", 80, 0, 0, 0, 0)


def test_ssrf_safe_context_invalid_url():
    with pytest.raises(ValueError), ssrf_safe_context("ftp://example.com"):
        pass
