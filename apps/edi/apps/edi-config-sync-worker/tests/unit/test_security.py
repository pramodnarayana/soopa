import socket
from collections.abc import Callable

import pytest
from edi.adapters.outbound.security import network
from edi.adapters.outbound.security.network import (
    get_safe_ip,
    ssrf_safe_context,
    validate_target_url,
)

PUBLIC_HOST = "public.example"
PUBLIC_IP = "93.184.216.34"


def resolver_for(addresses: dict[str, str]) -> Callable[..., list[tuple[object, ...]]]:
    def resolve(host: object, port: object, *_args: object) -> list[tuple[object, ...]]:
        host_text = str(host)
        address = addresses.get(host_text, host_text)
        if address == host_text and not address.replace(".", "").isdigit():
            raise socket.gaierror
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (address, port or 0))]

    return resolve


@pytest.fixture
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        network,
        "_orig_getaddrinfo",
        resolver_for({PUBLIC_HOST: PUBLIC_IP, "localhost": "127.0.0.1"}),
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


def test_validate_target_url_valid(public_dns: None) -> None:
    assert validate_target_url(f"http://{PUBLIC_HOST}")


def test_validate_target_url_private_ip() -> None:
    # Passing a raw private IP avoids needing DNS
    assert not validate_target_url("http://192.168.1.1")


def test_validate_target_url_loopback_ip(public_dns: None) -> None:
    assert not validate_target_url("http://localhost")


def test_get_safe_ip(public_dns: None) -> None:
    assert get_safe_ip(PUBLIC_HOST) == PUBLIC_IP


def test_get_safe_ip_private() -> None:
    assert get_safe_ip("192.168.1.1") is None


def test_ssrf_safe_context_valid(public_dns: None) -> None:
    with ssrf_safe_context(f"http://{PUBLIC_HOST}"):
        result = socket.getaddrinfo(PUBLIC_HOST, 80)
        assert result[0][4][0] == PUBLIC_IP


def test_ssrf_safe_context_invalid_url() -> None:
    with pytest.raises(ValueError), ssrf_safe_context("ftp://example.com"):
        pass
