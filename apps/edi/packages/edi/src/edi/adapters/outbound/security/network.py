import ipaddress
import socket
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from urllib.parse import urlparse

import structlog

from edi.config.settings import get_settings

logger = structlog.get_logger(__name__)

logger = structlog.get_logger(__name__)


def validate_target_url(url: str) -> bool:
    """
    Validate target URL to prevent SSRF attacks.
    Returns True if URL is safe, False otherwise.
    """
    try:
        parsed = urlparse(url)

        # Only allow http and https schemes
        if parsed.scheme not in ("http", "https"):
            logger.warning(
                "SSRF check failed: invalid scheme {parsed.scheme}", parsed_scheme=parsed.scheme
            )
            return False

        # Reject URLs without a hostname
        if not parsed.hostname:
            logger.warning("SSRF check failed: missing hostname")
            return False

        # Resolve all A/AAAA records for the hostname
        import socket

        try:
            # getaddrinfo returns a list of 5-tuples: (family, type, proto, canonname, sockaddr)
            addr_info = socket.getaddrinfo(parsed.hostname, None)
        except socket.gaierror:
            logger.warning(
                "SSRF check failed: could not resolve hostname {parsed.hostname}",
                parsed_hostname=parsed.hostname,
            )
            return False

        for addr in addr_info:
            ip_str = addr[4][0]
            ip = ipaddress.ip_address(ip_str)
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_reserved
                or ip.is_multicast
            ):
                from seedwork.constants import DeploymentEnvironment

                if get_settings().env == DeploymentEnvironment.DEVELOPMENT.value and ip.is_loopback:
                    pass
                else:
                    logger.warning("SSRF check failed: resolved to private/internal IP {ip}", ip=ip)
                    return False

        return True
    except Exception:
        logger.exception("SSRF validation error")

        return False


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


socket.getaddrinfo = _patched_getaddrinfo


def get_safe_ip(hostname: str) -> str | None:
    try:
        addr_info = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return None
    for addr in addr_info:
        sockaddr = addr[4]
        ip_str = str(sockaddr[0])
        ip = ipaddress.ip_address(ip_str)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            from seedwork.constants import DeploymentEnvironment

            if get_settings().env == DeploymentEnvironment.DEVELOPMENT.value and ip.is_loopback:
                return ip_str
            return None
        return ip_str
    return None


@contextmanager
def ssrf_safe_context(url: str) -> Iterator[None]:
    """
    Context manager that pins the validated IP address for the given URL's hostname
    to prevent DNS rebinding SSRF attacks.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("Invalid URL scheme or hostname for SSRF validation")

    safe_ip = get_safe_ip(parsed.hostname)
    if not safe_ip:
        raise ValueError(
            f"SSRF validation failed: unsafe or unresolvable hostname {parsed.hostname}"
        )

    token = _override_dns.set((parsed.hostname, safe_ip))
    try:
        yield
    finally:
        _override_dns.reset(token)
