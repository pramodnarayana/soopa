"""
Httpx-based AS2 connection tester adapter.

Sends a minimal synthetic X12 ISA envelope to the partner's AS2 URL,
then parses the synchronous MDN response. Used exclusively for the
"Test AS2 Partnership" support tool; never called in the production pipeline.
"""

import functools

import httpx
import structlog
from shttp import (
    HttpClient,
    HttpError,
    HttpNetworkError,
    HttpTimeoutError,
    SsrfSecurityError,
    create_http_client,
)

from edi.adapters.inbound.as2.builder import build_outbound_message
from edi.adapters.outbound.security import encrypt_payload, sign_payload
from edi.domain.services.as2_protocol import parse_mdn

logger = structlog.get_logger(__name__)


def build_synthetic_ping(as2_from: str, as2_to: str) -> bytes:
    """
    Builds a minimal, structurally valid X12 ISA/IEA envelope used as a test ping.
    Contains no real business data; purely for connectivity verification.
    """
    # X12 ISA requires exactly 15 characters, padded with spaces
    sender = as2_from.ljust(15)[:15]
    receiver = as2_to.ljust(15)[:15]
    return (
        f"ISA*00*          *00*          *ZZ*{sender}*ZZ*{receiver}"
        "*240101*1200*^*00501*000000001*0*T*:\n"
        "IEA*0*000000001\n"
    ).encode("ascii")


class HttpxAS2TesterAdapter:
    """
    Adapter that implements AS2TesterPort using HttpClient for the HTTP transport
    and the shared as2_core / security libraries for signing and encryption.

    Responsibility: transport only.
    - Returns (True, raw_mdn_disposition) when the remote partner responds with HTTP 200.
    - Returns (False, error_reason) on any transport or parse failure.
    The caller (router) is responsible for interpreting whether the MDN disposition
    constitutes a business-level success.
    """

    def __init__(
        self,
        allow_private_ips: bool = False,
        client: HttpClient | None = None,
    ) -> None:
        self.allow_private_ips = allow_private_ips
        self._owned_client = client is None
        if client is None:
            self._raw_client: httpx.AsyncClient | None = create_http_client(
                timeout=30.0,
                follow_redirects=False,
            )
            self._client = HttpClient(
                self._raw_client,
                allow_private_ips=allow_private_ips,
            )
        else:
            self._raw_client = None
            self._client = client

    async def test_connection(
        self,
        remote_url: str,
        as2_from: str,
        as2_to: str,
        local_private_key_pem: bytes | None,
        local_cert_pem: bytes | None,
        remote_cert_pem: bytes | None,
        encryption_algorithm: str,
        signature_algorithm: str,
        custom_payload: str | None = None,
    ) -> tuple[bool, str | None, str | None, str | None]:
        # Build sign/encrypt callables only if keys are available
        sign_fn = (
            functools.partial(
                sign_payload,
                private_key_pem=local_private_key_pem,
                public_cert_pem=local_cert_pem,
                algorithm=signature_algorithm,
            )
            if (local_private_key_pem and local_cert_pem)
            else None
        )
        encrypt_fn = (
            functools.partial(
                encrypt_payload,
                public_cert_pem=remote_cert_pem,
                algorithm=encryption_algorithm,
            )
            if remote_cert_pem
            else None
        )

        payload_bytes = (
            custom_payload.encode("utf-8")
            if custom_payload
            else build_synthetic_ping(as2_from, as2_to)
        )
        payload_str = payload_bytes.decode("utf-8", errors="replace")

        try:
            as2_msg = build_outbound_message(
                payload=payload_bytes,
                as2_from=as2_from,
                as2_to=as2_to,
                content_type="application/edi-x12",
                sign_fn=sign_fn,
                encrypt_fn=encrypt_fn,
            )
        except (ValueError, TypeError, KeyError, RuntimeError) as e:
            logger.error("as2_test_build_failed", error=str(e))
            return False, f"Failed to build AS2 message: {e}", payload_str, None

        try:
            response = await self._client.post(
                remote_url,
                content=as2_msg.body,
                headers=as2_msg.headers,
                timeout=30.0,
                allow_private_ips=self.allow_private_ips,
            )
        except (SsrfSecurityError, ValueError) as e:
            logger.error("as2_test_ssrf_blocked", url=remote_url, error=str(e))
            return False, f"SSRF validation failed for destination URL: {e}", payload_str, None
        except HttpTimeoutError as e:
            logger.error("as2_test_timeout", url=remote_url, error=str(e))
            return False, "Connection timed out after 30 seconds", payload_str, None
        except HttpNetworkError as e:
            cause = e.cause or e
            logger.error("as2_test_network_error", url=remote_url, error=str(cause))
            return False, f"Connection refused: {cause}", payload_str, None
        except (HttpError, httpx.RequestError) as e:
            logger.error("as2_test_http_error", url=remote_url, error=str(e))
            return False, f"HTTP error: {e}", payload_str, None

        raw_resp = response.content.decode("utf-8", errors="replace")
        headers_str = "\n".join(f"{k}: {v}" for k, v in response.headers.items())
        full_mdn = headers_str + "\n\n" + raw_resp

        if not (200 <= response.status_code < 300):
            logger.error(
                "as2_test_remote_status_error",
                url=remote_url,
                status_code=response.status_code,
            )
            return False, f"Remote returned HTTP {response.status_code}", payload_str, full_mdn

        content_type = response.headers.get("content-type", "").lower()
        # A signed MDN (multipart/signed) wraps the inner multipart/report in an S/MIME
        # signature envelope per RFC 4130 §7.4. Both are valid MDN responses.
        is_valid_mdn_content_type = (
            "multipart/report" in content_type or "multipart/signed" in content_type
        )
        if not is_valid_mdn_content_type:
            logger.error(
                "as2_test_invalid_mdn_content_type",
                url=remote_url,
                content_type=content_type,
            )
            return (
                False,
                f"MDN parse error: missing Content-Type multipart/report or multipart/signed, got {content_type}",
                payload_str,
                full_mdn,
            )

        try:
            mdn = parse_mdn(dict(response.headers), response.content)
            # Return raw disposition string — the caller decides if it is a success.
            # e.g. "automatic-action/MDN-sent-automatically; processed"
            return True, mdn.disposition or "", payload_str, full_mdn
        except (ValueError, KeyError, TypeError) as e:
            logger.error("as2_test_mdn_parse_failed", error=str(e))
            return False, f"MDN parse error: {e}", payload_str, full_mdn

    async def close(self) -> None:
        if self._owned_client and self._raw_client:
            await self._raw_client.aclose()
