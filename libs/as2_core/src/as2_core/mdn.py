"""
MDN (Message Disposition Notification) generation logic.
Calculates MIC (Message Integrity Check) and constructs the multipart/report.
"""

import base64
import hashlib
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
        digest = hashlib.sha1(payload).digest()
    elif alg == "md5":
        digest = hashlib.md5(payload).digest()
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
