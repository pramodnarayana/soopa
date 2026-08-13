"""
Outbound AS2 Message Builder.
Constructs an RFC 4130-compliant AS2 HTTP payload from raw EDI content.
"""

import email
import uuid
from dataclasses import dataclass, field
from typing import Any

from .mdn import calculate_mic


def _ensure_crlf(data: bytes) -> bytes:
    """
    Normalizes line endings to CRLF for MIME canonicalization, as required by
    AS2/S/MIME signatures.
    """
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n").replace(b"\n", b"\r\n")


@dataclass
class OutboundAS2Message:
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)
    mic: str | None = None


@dataclass
class _AS2State:
    payload: bytes
    content_type: str
    cte: str | None = None
    cd: str | None = None
    is_signed: bool = False
    is_encrypted: bool = False


def _apply_signature(state: _AS2State, sign_fn: Any) -> None:
    if sign_fn is None:
        return

    state.payload = sign_fn(state.payload)
    msg = email.message_from_bytes(state.payload)
    state.content_type = msg.get("Content-Type", "multipart/signed")
    state.cte = msg.get("Content-Transfer-Encoding") or state.cte
    state.cd = msg.get("Content-Disposition") or state.cd
    state.is_signed = True


def _apply_encryption(state: _AS2State, encrypt_fn: Any) -> None:
    if encrypt_fn is None:
        return

    state.payload = encrypt_fn(state.payload)
    msg = email.message_from_bytes(state.payload)

    encrypt_ct = msg.get("Content-Type")
    if encrypt_ct:
        state.content_type = encrypt_ct
    else:
        state.content_type = "application/pkcs7-mime; smime-type=enveloped-data; name=smime.p7m"

    state.cte = msg.get("Content-Transfer-Encoding") or state.cte
    state.cd = msg.get("Content-Disposition") or state.cd
    state.is_encrypted = True


def _build_headers(
    state: _AS2State,
    as2_from: str,
    as2_to: str,
    message_id: str | None,
    mic_alg: str,
    mdn_url: str | None,
) -> dict[str, str]:
    message_id_str = f"<{message_id}@soopaedi>" if message_id else f"<{uuid.uuid4()}@soopaedi>"
    headers: dict[str, str] = {
        "AS2-Version": "1.2",
        "AS2-From": as2_from,
        "AS2-To": as2_to,
        "Message-ID": message_id_str,
        "Content-Type": state.content_type,
        "MIME-Version": "1.0",
        "Disposition-Notification-To": as2_from,
        "Disposition-Notification-Options": f"signed-receipt-protocol=required, pkcs7-signature; signed-receipt-micalg=optional, {mic_alg}",
    }

    if state.cte:
        headers["Content-Transfer-Encoding"] = state.cte
    if state.cd:
        headers["Content-Disposition"] = state.cd
    if mdn_url:
        headers["Receipt-Delivery-Option"] = mdn_url

    return headers


def _strip_outer_mime_headers(payload: bytes, is_encrypted: bool, is_signed: bool) -> bytes:
    if not is_encrypted and not is_signed:
        return payload

    crlf_idx = payload.find(b"\r\n\r\n")
    lf_idx = payload.find(b"\n\n")

    # Choose the separator that occurs earliest (lowest index)
    if crlf_idx != -1 and lf_idx != -1:
        if crlf_idx < lf_idx:
            return payload.split(b"\r\n\r\n", 1)[1]
        else:
            return payload.split(b"\n\n", 1)[1]
    elif crlf_idx != -1:
        return payload.split(b"\r\n\r\n", 1)[1]
    elif lf_idx != -1:
        return payload.split(b"\n\n", 1)[1]
    return payload


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
    message_id: str | None = None,
) -> OutboundAS2Message:
    payload = _ensure_crlf(payload)

    if sign_fn is not None or encrypt_fn is not None:
        mime_headers = f"Content-Type: {content_type}\r\n"
        mime_headers += "Content-Transfer-Encoding: binary\r\n\r\n"
        payload = mime_headers.encode("ascii") + payload

    mic = calculate_mic(payload, mic_alg)

    state = _AS2State(payload=payload, content_type=content_type)

    _apply_signature(state, sign_fn)
    _apply_encryption(state, encrypt_fn)

    headers = _build_headers(state, as2_from, as2_to, message_id, mic_alg, mdn_url)
    final_payload = _strip_outer_mime_headers(state.payload, state.is_encrypted, state.is_signed)

    return OutboundAS2Message(
        body=final_payload,
        headers=headers,
        mic=mic,
    )
