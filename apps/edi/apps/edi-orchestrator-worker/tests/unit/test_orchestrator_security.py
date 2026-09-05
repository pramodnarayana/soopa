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
        if address == host_text and not (address.replace(".", "").isdigit() or ":" in address):
            raise socket.gaierror
        family = socket.AF_INET6 if ":" in address else socket.AF_INET
        socket_address = (
            (address, port or 0, 0, 0) if family == socket.AF_INET6 else (address, port or 0)
        )
        return [(family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", socket_address)]

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


def test_validate_target_url_private_ip(monkeypatch: pytest.MonkeyPatch) -> None:
    private_host = "private.example"
    monkeypatch.setattr(
        network,
        "_orig_getaddrinfo",
        resolver_for({private_host: "192.168.1.1"}),
    )
    assert not validate_target_url(f"http://{private_host}")


def test_validate_target_url_ipv6_link_local(monkeypatch: pytest.MonkeyPatch) -> None:
    local_host = "link-local.example"
    monkeypatch.setattr(
        network,
        "_orig_getaddrinfo",
        resolver_for({local_host: "fe80::1"}),
    )
    assert not validate_target_url(f"http://{local_host}")


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
