"""
AS2 Protocol Domain Services.

Pure business logic for the AS2 protocol:
  - MIC (Message Integrity Check) calculation
  - Request / MDN parsing
  - MDN generation and construction

All functions use only the Python stdlib (hashlib, base64, email, uuid).
No infrastructure or external library dependencies permitted here.
"""

import base64
import email
import hashlib
import uuid
from collections.abc import Callable

from seedwork import generate_random_hex

from edi.domain.models.as2 import AS2MDN, AS2Message, MDNResponse


def calculate_mic(payload: bytes, mic_alg: str = "sha256") -> str:
    """
    Calculates the Message Integrity Check (MIC) for an AS2 payload.

    Supported algorithms: sha256, sha1, md5 (sha1/md5 required for backward
    compatibility with older EDI trading partners per RFC 4130).
    """
    alg = mic_alg.lower().replace("-", "")

    if alg == "sha256":
        digest = hashlib.sha256(payload).digest()
    elif alg == "sha1":
        # AS2 RFC explicitly requires support for SHA1 for backwards compatibility.
        digest = hashlib.sha1(payload).digest()  # noqa: S324
    elif alg == "md5":
        # MD5 is heavily deprecated but still encountered in very old EDI implementations.
        digest = hashlib.md5(payload).digest()  # noqa: S324
    else:
        raise ValueError(f"Unsupported MIC algorithm: {mic_alg}")

    encoded_mic = base64.b64encode(digest).decode("ascii")
    return f"{encoded_mic}, {mic_alg}"


def parse_as2_request(headers: dict[str, str], raw_body: bytes) -> AS2Message:
    """
    Parses raw HTTP headers and body into an AS2Message value object.
    Identifies encryption, signing, and compression flags from Content-Type.
    """
    as2_from = headers.get("as2-from", "").strip(' "')
    as2_to = headers.get("as2-to", "").strip(' "')
    message_id = headers.get("message-id", "").strip(" <>")
    content_type = headers.get("content-type", "").lower()

    if not as2_from or not as2_to or not message_id:
        raise ValueError("Missing mandatory AS2 headers (as2-from, as2-to, message-id).")

    is_encrypted = "application/pkcs7-mime" in content_type and "enveloped-data" in content_type
    is_signed = "multipart/signed" in content_type or "application/pkcs7-signature" in content_type
    is_compressed = "application/pkcs7-mime" in content_type and "compressed-data" in content_type

    return AS2Message(
        message_id=message_id,
        as2_from=as2_from,
        as2_to=as2_to,
        headers=headers,
        payload=raw_body,
        is_encrypted=is_encrypted,
        is_signed=is_signed,
        is_compressed=is_compressed,
        raw_mime=raw_body,
    )


def parse_mdn(headers: dict[str, str], raw_body: bytes) -> AS2MDN:
    """
    Parses a raw MDN HTTP response (headers and body) into an AS2MDN value object.
    """
    headers_str = "\r\n".join(f"{k}: {v}" for k, v in headers.items())
    raw_msg_bytes = headers_str.encode("utf-8") + b"\r\n\r\n" + raw_body
    msg = email.message_from_bytes(raw_msg_bytes)

    disposition = ""
    received_mic = None
    original_message_id = ""

    for part in msg.walk():
        if part.get_content_type() == "message/disposition-notification":
            payload = part.get_payload()
            if isinstance(payload, list) and payload:
                disp_msg = payload[0]
                if isinstance(disp_msg, email.message.Message):
                    disposition = str(disp_msg.get("Disposition", ""))
                    received_mic = str(disp_msg.get("Received-content-MIC", ""))
                    original_message_id = str(disp_msg.get("Original-Message-ID", "")).strip(" <>")
            break

    return AS2MDN(
        original_message_id=original_message_id,
        disposition=disposition,
        headers=headers,
        mic=received_mic,
        is_signed=False,
    )


def generate_mdn(original_message: AS2Message, disposition: str, mic_alg: str = "sha256") -> AS2MDN:
    """
    Generates an AS2MDN value object from the original inbound AS2Message.
    MIC is calculated over the original payload.
    """
    mic = None
    if original_message.payload:
        mic = calculate_mic(original_message.payload, mic_alg)

    mdn_headers = {
        "AS2-From": original_message.as2_to,  # Swap To/From
        "AS2-To": original_message.as2_from,
        "Original-Message-ID": f"<{original_message.message_id}>",
    }

    return AS2MDN(
        original_message_id=original_message.message_id,
        disposition=disposition,
        headers=mdn_headers,
        mic=mic,
        is_signed=False,
    )


def build_mdn(
    as2_to: str,
    as2_from: str,
    message_id: str,
    disposition: str,
    mic: str | None = None,
    sign_fn: Callable[[bytes], bytes] | None = None,
) -> MDNResponse:
    """
    Constructs a serialized AS2 MDN HTTP response body and headers.

    If ``sign_fn`` is provided, the MDN body will be S/MIME-signed. The callable
    must accept raw bytes and return the signed MIME bytes. The application layer
    supplies this callable from the injected CryptoServicePort.
    """
    boundary = f"----=_Part_{generate_random_hex(6)}"

    lines = []
    lines.append(f"--{boundary}")
    lines.append("Content-Type: text/plain; charset=us-ascii")
    lines.append("Content-Transfer-Encoding: 7bit")
    lines.append("")
    lines.append("The AS2 message has been received successfully.")
    lines.append("")
    lines.append(f"--{boundary}")
    lines.append("Content-Type: message/disposition-notification")
    lines.append("Content-Transfer-Encoding: 7bit")
    lines.append("")
    lines.append("Reporting-UA: SoopaEDI")
    lines.append(f"Original-Recipient: rfc822; {as2_to}")
    lines.append(f"Final-Recipient: rfc822; {as2_to}")

    message_id_str = f"<{message_id}>" if not message_id.startswith("<") else message_id
    lines.append(f"Original-Message-ID: {message_id_str}")
    lines.append(f"Disposition: {disposition}")
    if mic:
        lines.append(f"Received-Content-MIC: {mic}")
    lines.append("")
    lines.append(f"--{boundary}--")
    lines.append("")

    inner_body = "\r\n".join(lines).encode("ascii")
    inner_content_type = (
        f'multipart/report; report-type=disposition-notification; boundary="{boundary}"'
    )

    headers = {
        "AS2-From": as2_to,
        "AS2-To": as2_from,
        "Message-ID": f"<mdn-{uuid.uuid4()}@soopa>",
        "Connection": "close",
    }

    if sign_fn:
        mime_entity = f"Content-Type: {inner_content_type}\r\n"
        mime_entity += "Content-Transfer-Encoding: binary\r\n\r\n"
        wrapped_body = mime_entity.encode("ascii") + inner_body

        signed_body = sign_fn(wrapped_body)

        msg = email.message_from_bytes(signed_body)
        signer_ct = msg.get("Content-Type") or "multipart/signed"
        headers["Content-Type"] = signer_ct

        if msg.get("Content-Transfer-Encoding"):
            headers["Content-Transfer-Encoding"] = str(msg.get("Content-Transfer-Encoding"))
        if msg.get("Content-Disposition"):
            headers["Content-Disposition"] = str(msg.get("Content-Disposition"))

        return MDNResponse(body=signed_body, headers=headers)
    else:
        headers["Content-Type"] = inner_content_type
        return MDNResponse(body=inner_body, headers=headers)
