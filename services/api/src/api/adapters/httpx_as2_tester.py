"""
Httpx-based AS2 connection tester adapter.

Sends a minimal synthetic X12 ISA envelope to the partner's AS2 URL,
then parses the synchronous MDN response. Used exclusively for the
"Test AS2 Partnership" support tool; never called in the production pipeline.
"""

import functools
import logging

import httpx
from as2_core import build_outbound_message, parse_mdn
from security import encrypt_payload, sign_payload

logger = logging.getLogger(__name__)


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
    Adapter that implements AS2TesterPort using httpx for the HTTP transport
    and the shared as2_core / security libraries for signing and encryption.

    Responsibility: transport only.
    - Returns (True, raw_mdn_disposition) when the remote partner responds with HTTP 200.
    - Returns (False, error_reason) on any transport or parse failure.
    The caller (router) is responsible for interpreting whether the MDN disposition
    constitutes a business-level success.
    """

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
        except Exception as e:
            logger.warning(f"as2_test_build_failed: {e}")
            return False, f"Failed to build AS2 message: {e}", payload_str, None

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    remote_url,
                    content=as2_msg.body,
                    headers=as2_msg.headers,
                )
        except httpx.ConnectError as e:
            return False, f"Connection refused: {e}", payload_str, None
        except httpx.TimeoutException:
            return False, "Connection timed out after 30 seconds", payload_str, None
        except Exception as e:
            return False, f"HTTP error: {e}", payload_str, None

        raw_resp = response.content.decode("utf-8", errors="replace")
        headers_str = "\n".join(f"{k}: {v}" for k, v in response.headers.items())
        full_mdn = headers_str + "\n\n" + raw_resp

        if not (200 <= response.status_code < 300):
            return False, f"Remote returned HTTP {response.status_code}", payload_str, full_mdn

        try:
            mdn = parse_mdn(dict(response.headers), response.content)
            # Return raw disposition string — the caller decides if it is a success.
            # e.g. "automatic-action/MDN-sent-automatically; processed"
            return True, mdn.disposition or "", payload_str, full_mdn
        except Exception as e:
            logger.warning(f"as2_test_mdn_parse_failed error={e}")
            return False, f"MDN parse error: {e}", payload_str, full_mdn
