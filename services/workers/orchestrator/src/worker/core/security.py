import ipaddress
import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def validate_target_url(url: str) -> bool:
    """
    Validate target URL to prevent SSRF attacks.
    Returns True if URL is safe, False otherwise.
    """
    try:
        parsed = urlparse(url)

        # Only allow http and https schemes
        if parsed.scheme not in ("http", "https"):
            logger.warning(f"SSRF check failed: invalid scheme {parsed.scheme}")
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
            logger.warning(f"SSRF check failed: could not resolve hostname {parsed.hostname}")
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
                logger.warning(f"SSRF check failed: resolved to private/internal IP {ip}")
                return False

        return True
    except Exception as e:
        logger.error(f"SSRF validation error: {e}")
        return False
