from collections.abc import Callable

import httpx
from pipeline.ports.http import HttpDeliveryPort


class HttpxDeliveryAdapter(HttpDeliveryPort):
    """
    Concrete implementation of HttpDeliveryPort using HTTPX.
    """

    def __init__(self, timeout_secs: int = 30, validator: Callable[[str], bool] | None = None):
        self.timeout = timeout_secs
        self.validator = validator

    async def deliver(self, url: str, payload: bytes, auth_token: str | None = None) -> int:
        if self.validator and not self.validator(url):
            raise ValueError("URL validation failed for provided destination.")

        import ipaddress
        import socket
        from urllib.parse import urlparse

        import anyio

        parsed = urlparse(url)
        if not parsed.hostname:
            raise ValueError("Invalid URL")

        addr_info = await anyio.to_thread.run_sync(socket.getaddrinfo, parsed.hostname, None)
        ip = addr_info[0][4][0]
        ip_obj = ipaddress.ip_address(ip)
        if (
            ip_obj.is_private
            or ip_obj.is_loopback
            or ip_obj.is_unspecified
            or ip_obj.is_link_local
            or ip_obj.is_reserved
            or ip_obj.is_multicast
        ):
            raise ValueError("SSRF check failed: internal IP")

        port_str = f":{parsed.port}" if parsed.port else ""
        safe_url = parsed._replace(netloc=f"{ip}{port_str}").geturl()

        headers = {"Content-Type": "application/json", "Host": parsed.hostname}
        if auth_token:
            headers["Authorization"] = auth_token

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=False) as client:
            response = await client.post(safe_url, content=payload, headers=headers)
            return response.status_code
