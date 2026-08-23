from typing import Protocol


class AS2DeliveryPort(Protocol):
    """
    Interface for executing an outbound AS2 HTTP POST transmission.
    The implementation handles the transport only — headers and body
    are pre-built by the as2_core builder.
    """

    async def deliver(
        self,
        url: str,
        body: bytes,
        headers: dict[str, str],
    ) -> tuple[int, dict[str, str], bytes]:
        """
        Sends the AS2 POST request to the remote trading partner.

        Args:
            url:     The remote AS2 endpoint URL (remote_url in AS2Partnership).
            body:    The pre-built S/MIME body bytes (signed, encrypted, or plain).
            headers: The AS2 HTTP headers dict (AS2-From, AS2-To, Message-ID, etc.).

        Returns:
            A tuple of (http_status_code, response_headers, response_body_bytes).
            The caller is responsible for parsing the MDN from the response body.
        """
        ...
