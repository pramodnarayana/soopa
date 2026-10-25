"""Security utilities for SFTP host and address validation (SSRF defense)."""

from __future__ import annotations

import ipaddress
import socket

import structlog

from sftp.exceptions import SftpHostValidationError

logger = structlog.get_logger(__name__)


def resolve_and_validate_host(
    host: str,
    port: int = 22,
    allow_local: bool = False,
) -> list[str]:
    """Resolves an SFTP hostname and validates that each IP address is globally routable.

    Blocks SSRF attacks against internal cloud metadata endpoints (e.g. 169.254.169.254)
    and internal VPC networks.
    """
    clean_host = host.strip()
    if not clean_host:
        raise SftpHostValidationError("Host cannot be empty.")

    try:
        addr_infos = socket.getaddrinfo(clean_host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        logger.error("sftp_dns_resolution_failed", host=clean_host, error=str(exc))
        raise SftpHostValidationError(f"Failed to resolve host '{clean_host}': {exc}") from exc

    if not addr_infos:
        raise SftpHostValidationError(f"No addresses resolved for host '{clean_host}'")

    validated_ips: list[str] = []
    for _family, _type, _proto, _canonname, sockaddr in addr_infos:
        ip_str = str(sockaddr[0])
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError as exc:
            raise SftpHostValidationError(
                f"Unparsable IP address '{ip_str}' for host '{clean_host}'"
            ) from exc

        if not allow_local and not ip.is_global:
            logger.error(
                "sftp_ssrf_blocked",
                host=clean_host,
                resolved_ip=ip_str,
            )
            raise SftpHostValidationError(
                f"SSRF blocked: host '{clean_host}' resolved to non-global address '{ip_str}'"
            )

        validated_ips.append(ip_str)

    return validated_ips
