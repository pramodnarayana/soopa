"""
Outbound AS2 Message Builder.
Constructs an RFC 4130-compliant AS2 HTTP payload from raw EDI content.

Workflow (per RFC 4130 Section 3.1):
  1. Start with raw EDI payload.
  2. Compute MIC *before* any wrapping (on the innermost MIME entity).
  3. Optionally sign   → multipart/signed or application/pkcs7-mime (opaque-signed)
  4. Optionally encrypt → application/pkcs7-mime (enveloped-data)
  5. Return the final bytes + the HTTP headers the sender must set.
"""

import uuid
from dataclasses import dataclass, field

from .mdn import calculate_mic


@dataclass
class OutboundAS2Message:
    """
    Result of building an outbound AS2 message.
    Contains the final HTTP body bytes and the headers to send.
    """

    body: bytes
    """Raw bytes to send as the HTTP POST body."""

    headers: dict[str, str] = field(default_factory=dict)
    """HTTP headers required for the AS2 transmission."""

    mic: str | None = None
    """Pre-encryption MIC, to be stored for MDN validation."""


def build_outbound_message(
    *,
    payload: bytes,
    as2_from: str,
    as2_to: str,
    content_type: str = "application/edi-x12",
    sign_fn: object | None = None,
    encrypt_fn: object | None = None,
    mdn_url: str | None = None,
    mic_alg: str = "sha256",
) -> OutboundAS2Message:
    """
    Builds a fully-wrapped, optionally signed, optionally encrypted AS2
    HTTP payload, following RFC 4130 and OpenAS2 inter-op conventions.

    Args:
        payload:      Raw EDI content bytes (e.g., ISA...IEA for X12).
        as2_from:     Local AS2 partner ID (AS2-From header value).
        as2_to:       Remote AS2 partner ID (AS2-To header value).
        content_type: MIME type of the payload, defaults to EDI-X12.
        sign_fn:      Optional callable(payload, ...) → signed_bytes.
                      If provided, the payload is signed before encrypting.
        encrypt_fn:   Optional callable(payload) → encrypted_bytes.
                      If provided, the (possibly-signed) payload is encrypted.
        mdn_url:      If set, requests an async MDN at this URL.
                      If None, requests a synchronous (inline) MDN.
        mic_alg:      Hash algorithm for MIC computation (sha1 or sha256).

    Returns:
        OutboundAS2Message with body bytes and AS2 HTTP headers.
    """
    # ── Step 1: Compute MIC on the *raw* payload before any wrapping ─────────
    mic = calculate_mic(payload, mic_alg)

    # ── Step 2: Optionally sign ───────────────────────────────────────────────
    current_payload = payload
    current_content_type = content_type
    is_signed = False

    if sign_fn is not None:
        current_payload = sign_fn(current_payload)  # type: ignore[operator]
        # Signed output from security.sign_payload is multipart/signed SMIME
        current_content_type = "multipart/signed"
        is_signed = True

    # ── Step 3: Optionally encrypt ────────────────────────────────────────────
    is_encrypted = False
    if encrypt_fn is not None:
        current_payload = encrypt_fn(current_payload)  # type: ignore[operator]
        current_content_type = "application/pkcs7-mime; smime-type=enveloped-data; name=smime.p7m"
        is_encrypted = True

    # ── Step 4: Build HTTP Headers ────────────────────────────────────────────
    message_id = f"<{uuid.uuid4()}@soopaedi>"
    headers: dict[str, str] = {
        "AS2-Version": "1.2",
        "AS2-From": as2_from,
        "AS2-To": as2_to,
        "Message-ID": message_id,
        "Content-Type": current_content_type,
        "MIME-Version": "1.0",
        "Disposition-Notification-To": as2_from,
        "Disposition-Notification-Options": f"signed-receipt-protocol=required, pkcs7-signature; signed-receipt-micalg=optional, {mic_alg}",
    }

    if mdn_url:
        # Async MDN: send back to this URL
        headers["Receipt-Delivery-Option"] = mdn_url
    # else: sync MDN is the default — the response body itself is the MDN

    # Encode security flags for the receiver to know what to expect
    security_note_parts = []
    if is_encrypted:
        security_note_parts.append("encrypted")
    if is_signed:
        security_note_parts.append("signed")

    return OutboundAS2Message(
        body=current_payload,
        headers=headers,
        mic=mic,
    )
