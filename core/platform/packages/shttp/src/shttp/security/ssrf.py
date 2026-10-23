"""SSRF protection, private IP blocking, and DNS rebinding prevention."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from urllib.parse import urlparse

import structlog

from ..exceptions import SsrfSecurityError, SsrfViolationReason

logger = structlog.get_logger(__name__)

_override_dns: ContextVar[tuple[str, str] | None] = ContextVar("override_dns", default=None)
_orig_getaddrinfo = socket.getaddrinfo


def _patched_getaddrinfo(
    host: bytes | str | None,
    port: bytes | str | int | None,
    family: int = 0,
    type: int = 0,
    proto: int = 0,
    flags: int = 0,
) -> list[
    tuple[
        socket.AddressFamily,
        socket.SocketKind,
        int,
        str,
        tuple[str, int] | tuple[str, int, int, int] | tuple[int, bytes],
    ]
]:
    override = _override_dns.get()
    if override and host == override[0]:
        return _orig_getaddrinfo(override[1], port, family, type, proto, flags)
    return _orig_getaddrinfo(host, port, family, type, proto, flags)


# Apply idempotent socket patching
socket.getaddrinfo = _patched_getaddrinfo


def is_ip_private_or_restricted(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Checks whether an IP address belongs to private, loopback, link-local, multicast, or reserved ranges."""
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def is_allowed_private_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Allowed private addresses (RFC 1918 and loopback) when allow_private_ips is True.

    Link-local (e.g. AWS IMDS 169.254.169.254, fe80::), multicast, and reserved addresses are strictly forbidden.
    """
    if ip.is_link_local or ip.is_multicast or ip.is_unspecified:
        return False
    if ip.is_reserved and not ip.is_loopback:
        return False
    return bool(ip.is_private or ip.is_loopback)


def validate_target_url(url: str, allow_private_ips: bool = False) -> bool:
    """Validates target URL scheme, hostname, and resolved IP addresses to prevent SSRF attacks."""
    try:
        parsed = urlparse(url)

        # 1. Enforce HTTP and HTTPS schemes only
        if parsed.scheme not in ("http", "https"):
            logger.error("ssrf_check_invalid_scheme", parsed_scheme=parsed.scheme, url=url)
            return False

        # 2. Reject URLs without hostname
        if not parsed.hostname:
            logger.error("ssrf_check_missing_hostname", url=url)
            return False

        # 3. Resolve all A and AAAA records for the hostname
        try:
            addr_info = socket.getaddrinfo(parsed.hostname, None)
        except socket.gaierror as exc:
            logger.error(
                "ssrf_check_unresolvable_hostname",
                hostname=parsed.hostname,
                error=str(exc),
            )
            return False

        for addr in addr_info:
            ip_str = addr[4][0]
            try:
                ip = ipaddress.ip_address(ip_str)
            except ValueError:
                return False

            if is_ip_private_or_restricted(ip):
                if allow_private_ips and is_allowed_private_ip(ip):
                    continue
                logger.error(
                    "ssrf_check_restricted_ip_blocked",
                    hostname=parsed.hostname,
                    resolved_ip=str(ip),
                )
                return False

        return True
    except (ValueError, OSError) as exc:
        logger.error("ssrf_validation_network_failure", url=url, error=str(exc))
        return False


def get_safe_ip(hostname: str, allow_private_ips: bool = False) -> str | None:
    """Resolves and returns the first safe public IP for the given hostname."""
    try:
        addr_info = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return None

    for addr in addr_info:
        sockaddr = addr[4]
        ip_str = str(sockaddr[0])
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue

        if is_ip_private_or_restricted(ip):
            if allow_private_ips and is_allowed_private_ip(ip):
                return ip_str
            continue
        return ip_str
    return None


@contextmanager
def ssrf_safe_context(url: str, allow_private_ips: bool = False) -> Iterator[None]:
    """Context manager that pins the validated IP address for the given URL hostname

    to prevent DNS rebinding TOCTOU SSRF attacks during the HTTP request execution.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise SsrfSecurityError(
            f"Invalid URL scheme '{parsed.scheme}'; only 'http' and 'https' are permitted",
            url=url,
            reason=SsrfViolationReason.INVALID_SCHEME,
        )
    if not parsed.hostname:
        raise SsrfSecurityError(
            f"Missing hostname in target URL '{url}'",
            url=url,
            reason=SsrfViolationReason.MISSING_HOSTNAME,
        )

    try:
        addr_info = socket.getaddrinfo(parsed.hostname, None)
    except socket.gaierror as exc:
        raise SsrfSecurityError(
            f"DNS resolution failed for target host '{parsed.hostname}'",
            url=url,
            reason=SsrfViolationReason.UNRESOLVABLE_HOST,
            cause=exc,
        ) from exc

    safe_ip: str | None = None
    for addr in addr_info:
        sockaddr = addr[4]
        ip_str = str(sockaddr[0])
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue

        if is_ip_private_or_restricted(ip):
            if allow_private_ips and is_allowed_private_ip(ip):
                safe_ip = ip_str
                break
            continue
        safe_ip = ip_str
        break

    if not safe_ip:
        raise SsrfSecurityError(
            f"SSRF validation failed: host '{parsed.hostname}' resolved exclusively to restricted IP addresses",
            url=url,
            reason=SsrfViolationReason.RESTRICTED_IP,
        )

    token = _override_dns.set((parsed.hostname, safe_ip))
    try:
        yield
    finally:
        _override_dns.reset(token)
