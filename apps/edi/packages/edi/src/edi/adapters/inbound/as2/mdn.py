"""
MDN (Message Disposition Notification) generation logic.
Calculates MIC (Message Integrity Check) and constructs the multipart/report.
"""

import base64
import email
import hashlib
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from .message import AS2MDN, AS2Message


class Disposition(StrEnum):
    PROCESSED = "automatic-action/MDN-sent-automatically; processed"
    DECRYPTION_FAILED = "automatic-action/MDN-sent-automatically; failed/decryption-failed"
    AUTHENTICATION_FAILED = "automatic-action/MDN-sent-automatically; failed/authentication-failed"
    INSUFFICIENT_SECURITY = (
        "automatic-action/MDN-sent-automatically; failed/insufficient-message-security"
    )


def calculate_mic(payload: bytes, mic_alg: str = "sha256") -> str:
    """
    Calculates the Message Integrity Check (MIC) for an AS2 payload.
    """
    alg = mic_alg.lower().replace("-", "")

    if alg == "sha256":
        digest = hashlib.sha256(payload).digest()
    elif alg == "sha1":
        # AS2 RFC explicitly requires support for older MIC algorithms like SHA1 for backwards compatibility.
        digest = hashlib.sha1(payload).digest()  # noqa: S324
    elif alg == "md5":
        # MD5 is heavily deprecated but still encountered in very old EDI implementations.
        digest = hashlib.md5(payload).digest()  # noqa: S324
    else:
        raise ValueError(f"Unsupported MIC algorithm: {mic_alg}")

    encoded_mic = base64.b64encode(digest).decode("ascii")
    return f"{encoded_mic}, {mic_alg}"


def generate_mdn(original_message: AS2Message, disposition: str, mic_alg: str = "sha256") -> AS2MDN:
    """
    Generates an MDN representing the disposition of the received AS2 message.
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
        is_signed=False,  # Will be signed later if requested via disposition-notification-options
    )


@dataclass
class MDNResponse:
    body: bytes
    headers: dict[str, str]


def build_mdn(
    as2_to: str,
    as2_from: str,
    message_id: str,
    disposition: str,
    mic: str | None = None,
    sign_fn: Callable[[bytes], bytes] | None = None,
) -> MDNResponse:
    boundary = f"----=_Part_{uuid.uuid4().hex}"

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

    # if message_id isn't wrapped in <>, wrap it, otherwise use it directly
    message_id_str = f"<{message_id}>" if not message_id.startswith("<") else message_id

    lines.append(f"Original-Message-ID: {message_id_str}")
    lines.append(f"Disposition: {disposition}")
    if mic:
        lines.append(f"Received-Content-MIC: {mic}")
    lines.append("")
    lines.append(f"--{boundary}--")
    lines.append("")

    # Construct the inner multipart/report body and headers
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
        # Wrap inner body into a proper MIME entity
        mime_entity = f"Content-Type: {inner_content_type}\r\n"
        mime_entity += "Content-Transfer-Encoding: binary\r\n\r\n"
        wrapped_body = mime_entity.encode("ascii") + inner_body

        signed_body = sign_fn(wrapped_body)

        # Parse the signer's output to extract the correct Content-Type (which includes micalg and signature boundary)
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
